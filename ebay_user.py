# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import os
import sys
import logging
from datetime import datetime, timedelta, tzinfo
import dateutil.parser as parser
from dateutil.relativedelta import relativedelta
from operator import itemgetter
import time
import pytz

from openerp import SUPERUSER_ID
from openerp import pooler, tools
from openerp.osv import fields, osv, orm
from openerp.tools.translate import _
from openerp.tools.float_utils import float_round

import openerp.addons.decimal_precision as dp

import base64
import urllib2

import json

import ebaysdk
from ebaysdk.exception import ConnectionError, ConnectionResponseError
from requests.exceptions import RequestException

_logger = logging.getLogger(__name__)

class ebay_user_authorize(osv.TransientModel):
    _name = 'ebay.user.authorize'
    _description = 'eBay User Authentication'
    
    _columns = {
        'user_id': fields.many2one('ebay.user', 'User', readonly=True),
        'session_id': fields.char('SessionID', size=40, readonly=True),
        'sign_in_url': fields.char('SignInUrl', size=256, readonly=True),
        'state': fields.selection([
            ('confirm', 'confirm'),
            ('login', 'login')]),
    }
    
    _defaults = {
        'state': 'confirm',
    }
    
    def get_session_id(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        this = self.browse(cr, uid, ids)[0]
        
        record_id = context and context.get('active_id', False)
        user = self.pool.get('ebay.user').browse(cr, uid, record_id, context=context)
        call_data = dict(
            RuName=user.ru_name,
        )
        error_msg = 'Get Session ID failed the specified user %s' % user.name
        reply = self.pool.get('ebay.ebay').call(cr, uid, user, 'GetSessionID', call_data, error_msg, context=context).response.reply
        session_id = reply.SessionID
        sign_in_url = self.pool.get('ebay.ebay').get_ebay_sign_in_url(cr, uid, user.sale_site, user.sandbox, user.ru_name, session_id)
        
        self.write(cr, uid, ids, {'user_id': record_id,
                                  'session_id': session_id,
                                  'sign_in_url': sign_in_url,
                                  'state': 'login'}, context=context)
        
        return {
            'name': "eBay User Authentication",
            'type': 'ir.actions.act_window',
            'res_model': 'ebay.user.authorize',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': this.id,
            'views': [(False, 'form')],
            'target': 'new',
        }
    
    def fetch_token(self, cr, uid, ids, context=None):
        
        if context is None:
            context = {}
        this = self.browse(cr, uid, ids)[0]
        user = this.user_id
        call_data = dict(
            SessionID=this.session_id,
        )
        error_msg = 'Fetch token failed for the user %s' % user.name
        reply = self.pool.get('ebay.ebay').call(cr, uid, user, 'FetchToken', call_data, error_msg, context=context).response.reply
        user.write(dict(
            ebay_auth_token=reply.eBayAuthToken,
            hard_expiration_time=reply.HardExpirationTime,
            #rest_token=reply.RESTToken
        ))
        
        return {'type': 'ir.actions.act_window',
            'view_mode': 'form,tree',
            'view_type': 'form',
            'res_model': 'ebay.user',
            'res_id': user.id}

ebay_user_authorize()

class ebay_user(osv.osv):
    _name = "ebay.user"
    _description = "a registered eBay user"
    
    @staticmethod
    def get_shipping_service_type():
        return [
            ('usps', _('United States Postal Service')),
            ('fedex', _('FedEx')),
            ('ups', _('United Parcel Service')),
        ]
    def _get_shipping_service_type(self, cr, uid, context=None):
        return self.get_shipping_service_type()
    
    _columns = {
        'email': fields.char('Email', size=128, readonly=True),
        'feedback_rating_star': fields.selection([
            ('Blue', 'Blue Star'),
            ('CustomCode', 'Reserved for internal or future use.'),
            ('Green', 'Green Star'),
            ('GreenShooting','Green Shooting Star'),
            ('None', 'No graphic displayed'),
            ('Purple', 'Purple Star'),
            ('PurpleShooting', 'Purple Shooting Star'),
            ('Red', 'Red Star'),
            ('RedShooting', 'Red Shooting Star'),
            ('SilverShooting', 'Silver Shooting Star'),
            ('Turquoise', 'Turquoise Star'),
            ('TurquoiseShooting', 'Turquoise Shooting Star'),
            ('Yellow', 'Yellow Star'),
            ('YellowShooting', 'Yellow Shooting Star')
            ], 'Feedback Rating Star', readonly=True),
        'feedback_score': fields.integer('Feedback Score', readonly=True),
        'positive_feedback_percent': fields.float('Feedback Percent', readonly=True),
        'registration_date': fields.datetime('Registration Date', readonly=True),
        'store_owner': fields.boolean('Store Owner', readonly=True),
        'store_site': fields.char('Store Site', readonly=True),
        'store_url': fields.char('Store URL', readonly=True),
        'top_rated_seller': fields.boolean('Top-rated Seller', readonly=True),
        'site': fields.char('Site', readonly=True),
        'unique_negative_feedback_count': fields.integer('Negative', readonly=True),
        'unique_neutral_feedback_count': fields.integer('Neutral', readonly=True),
        'unique_positive_feedback_count': fields.integer('Positive', readonly=True),
        'name': fields.char('User ID', required=True, select=True),
        # Selleris
        'seller_list_ids': fields.one2many('ebay.seller.list', 'user_id', 'Seller Lists', readonly=True),
        'last_updated': fields.datetime('Last Updated'),
        # Application keys for authorization
        'ownership': fields.boolean('Ownership', readonly=True),
        'sandbox': fields.boolean('Sandbox'),
        'sale_site': fields.selection([
            ('0', 'US'),
            ('1', 'Germany'),
            ('2', 'Canada'),
            ('3', 'UK'),
            ('15', 'Australia'),
            ('201', 'HongKong'),
            ], 'Sale Site'),
        'app_id': fields.char('AppID', size=64),
        'dev_id': fields.char('DevID', size=64),
        'cert': fields.char('CERT', size=64),
        'ru_name': fields.text('RuName', size=1024),
        # Auth info, get from FetchToken
        'ebay_auth_token': fields.char('eBayAuthToken', readonly=True),
        'hard_expiration_time': fields.datetime('HardExpirationTime', readonly=True),
        'rest_token': fields.char('RESTToken', readonly=True),
        # Sale status
        'monthly_sales': fields.float('Monthly Sales', readonly=True),
        'monthly_sales_volume': fields.integer('Monthly Sales Volume', readonly=True),
        # Additional Info
        'ebay_item_ids': fields.one2many('ebay.item', 'ebay_user_id', 'Items'),
        'paypal_email_address': fields.char('Paypal Email Address'),
        'country': fields.char('Country', size=2),
        'location': fields.char('Location'),
        'shipping_service': fields.selection(
            _get_shipping_service_type, 'Shipping service'
        ),
        'after_service_7_template': fields.text('7 days template'),
        'after_service_15_template': fields.text('15 days template'),
        'after_service_25_template': fields.text('25 days template'),
        # User Preferences
        'exclude_ship_to_location': fields.text('Exclude Ship To Location', readonly=True),
    }
    
    _defaults = {
        'feedback_score': 0,
        'store_owner': 0,
        'ownership': 0,
        'sandbox': 0,
        'sale_site': '0',
        'country': 'USA',
        'location': 'Toledo',
        'shipping_service': 'usps',
        'after_service_7_template': '''
Hi friend.
  Your item has been shipped on {{ shipped_time }} by USPS,
  and it may take about 1 to 3 working days to arrive,
  sometimes it may be delayed by unexpected reason like holiday,
  custom`s process, weather condition etc.
  It may be delayed up to 7 days to arrive.
  We will be very appreciated for your patience.
  If you have any question, feel free to contact us.
  Thank you for your purchase.
  
  Yours Sincerely
''',
        'after_service_15_template': '''
Hi friend.
  Your item has been shipped on {{ shipped_time }} by DPD.
  {{ elapse }} days have passed since your item was shipped,
  When you receive it, we sincerely hope that you will like it 
  and appreciate our customer services.
  If there is anything you feel unsatisfied with, please do tell us. 
  This will help us know what we should do to help you as well as how we should improve.
  If you are satisfied, we sincerely hope that you can leave us a positive comment, 
  which is of vital importance to the growth of our small company.
  PLEASE DO NOT leaves us negative feedback. If you are not satisfied in any regard,
  please tell us.
  Thanks once more for your purchase.
  
  Yours Sincerely
''',
        'after_service_25_template': '''
Hi friend.
  Your item has been shipped on {{ shipped_time }} by DPD.
  If you haven't received your item and this situation lasts to the 30th day,
  please do contact us. WE WILL DO OUR BEST TO SOLVE YOUR PROBLEM.
  We do not want to give you a bad buying experience even when the shipping is out of our control.
  But if you receive it, we sincerely hope you can leave us a positive comment if you like it and
  appreciate our customer services.
  Thanks once more for your purchase.

  Yours Sincerely
'''
    }
    
    _order = 'monthly_sales desc'
    
    _sql_constraints = [
        ('name_uniq', 'unique(name, sandbox)', 'User ID must be unique!'),
    ]
    
    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        
        name = self.read(cr, uid, id, ['name'], context=context)['name']
        default = default.copy()
        default.update({
            'name': name + _(' (Copy)'),
            'session_id': '',
            'ebay_auth_token': '',
        })

        return super(ebay_user, self).copy(cr, uid, id, default, context)
    
    def action_get_user(self, cr, uid, ids, context=None):
        for user in self.browse(cr, uid, ids, context=context):
            call_data=dict()
            call_data['UserID'] = user.name
            error_msg = 'Get the data for the specified user %s' % user.name
            reply = self.pool.get('ebay.ebay').call(cr, uid, user, 'GetUser', call_data, error_msg, context=context).response.reply
            vals = dict()
            user_dict = reply.User
            vals['email'] = user_dict.Email
            vals['feedback_rating_star'] = user_dict.FeedbackRatingStar
            vals['feedback_score'] = user_dict.FeedbackScore
            vals['positive_feedback_percent'] = user_dict.PositiveFeedbackPercent
            vals['registration_date'] = user_dict.RegistrationDate
            seller_info = user_dict.SellerInfo
            vals['store_owner'] = seller_info.StoreOwner == "true"
            if vals['store_owner']:
                vals['store_site'] = seller_info.StoreSite
                vals['store_url'] = seller_info.StoreURL
            vals['top_rated_seller'] = seller_info.get('TopRatedSeller', False)
            vals['site'] = user_dict.Site
            vals['unique_negative_feedback_count'] = user_dict.UniqueNegativeFeedbackCount
            vals['unique_neutral_feedback_count'] = user_dict.UniqueNeutralFeedbackCount
            vals['unique_positive_feedback_count'] = user_dict.UniquePositiveFeedbackCount
            
            call_data=dict()
            call_data['ShowSellerExcludeShipToLocationPreference'] = 'true'
            error_msg = 'Get the user perferences for the user %s' % user.name
            reply = self.pool.get('ebay.ebay').call(cr, uid, user, 'GetUserPreferences', call_data, error_msg, context=context).response.reply
            exclude_ship_to_location = reply.SellerExcludeShipToLocationPreferences.ExcludeShipToLocation
            if type(exclude_ship_to_location) != list:
                vals['exclude_ship_to_location'] = exclude_ship_to_location
            else:
                vals['exclude_ship_to_location'] = '|'.join(exclude_ship_to_location)
                
            user.write(vals)
    
    def action_get_seller_list(self, cr, uid, ids, context=None):
        ebay_seller_list_obj = self.pool.get('ebay.seller.list')
        
        try:
            for user in self.browse(cr, uid, ids, context=context):
                ebay_seller_list_obj.get_seller_list(cr, uid, user, context=context)
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'GetSellerList', e, context=context)
        else:
            return True
            
ebay_user()
