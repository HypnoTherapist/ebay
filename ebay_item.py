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

import sys
import io
import base64
import urllib2
import uuid
import logging
from datetime import datetime, timedelta
import time

from jinja2 import Template

from openerp import SUPERUSER_ID
from openerp import pooler, tools
from openerp.osv import fields, osv, orm
from openerp.tools.translate import _
from openerp.tools.float_utils import float_round

import openerp.addons.decimal_precision as dp

import ebaysdk
from openerp.addons.ebay.ebay_utils import *
from ebaysdk.exception import ConnectionError, ConnectionResponseError
from requests.exceptions import RequestException

_logger = logging.getLogger(__name__)

class ebay_details(osv.osv):
    _name = "ebay.details"
    _description = "eBay details"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'site_id': fields.selection([
            ('0', 'US'),
            ('1', 'Germany',),
            ('2', 'Canada',),
            ('3', 'UK'),
            ('15', 'Australia'),
            ('201', 'HongKong'),
        ], 'Site', required=True),
        'sandbox': fields.boolean('Sandbox'),
        # Category Feature
        'ebay_details': fields.text('eBay Details', readonly=True),
    }
    
    _defaults = {
        'name': 'ebay details',
        'site_id': '0',
        'sandbox': False
    }
    
    def action_update(self, cr, uid, ids, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        for details in self.browse(cr, uid, ids, context=context):
            user = ebay_ebay_obj.get_arbitrary_auth_user(cr, uid, details.sandbox)
            call_data = dict()
            error_msg = 'Get the ebay details list for %s site' % details.site_id
            resp = self.pool.get('ebay.ebay').call(cr, uid, user, 'GeteBayDetails', call_data, error_msg, context=context).response_content()
            details.write(dict(ebay_details=resp))
    
ebay_details()

class ebay_category(osv.osv):
    _name = "ebay.category"
    _description = "eBay category"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'category_site_id': fields.selection([
            ('0', 'US'),
            ('1', 'Germany',),
            ('2', 'Canada',),
            ('3', 'UK'),
            ('15', 'Australia'),
            ('201', 'HongKong'),
        ], 'Category Site', required=True),
        'sandbox': fields.boolean('Sandbox'),
        'category_id': fields.char('Category ID', size=10, required=True),
        # Category Feature
        'condition_enabled': fields.char('ConditionEnabled', readonly=True),
        'condition_values': fields.text('ConditionValues'),
        'free_gallery_plus_enabled': fields.boolean('FreeGalleryPlusEnabled', readonly=True),
        'free_picture_pack_enabled': fields.boolean('FreePicturePackEnabled', readonly=True),
        'handling_time_enabled': fields.boolean('HandlingTimeEnabled', readonly=True),
        'item_specifics_enabled': fields.char('ItemSpecificsEnabled', readonly=True),
        'variations_enabled': fields.boolean('VariationsEnabled', readonly=True),
        'category_feature': fields.text('Category Feature', readonly=True),
    }
    
    _defaults = {
        'category_site_id': '0',
        'sandbox': False
    }
    
    _sql_constraints = [
        ('category_id_uniq', 'unique(category_id, sandbox)', 'Category ID must be unique!'),
    ]
    
    def search_category(self, cr, uid, category_id, category_name, sandbox, context=None):
        domain = [('category_id', '=', category_id), ('sandbox', '=', sandbox)]
        ids = self.search(cr, uid, domain, context=context)
        if ids:
            id = ids[0]
        else:
            vals = dict(
                name=category_name,
                category_id=category_id,
                sandbox=sandbox,
            )
            id = self.create(cr, uid, vals, context=context)
        return id
    
    def action_update(self, cr, uid, ids, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        for category in self.browse(cr, uid, ids, context=context):
            user = ebay_ebay_obj.get_arbitrary_auth_user(cr, uid, category.sandbox)
            call_data = dict()
            call_data['AllFeaturesForCategory'] = True
            call_data['CategoryID'] = category.category_id
            call_data['ViewAllNodes'] = True
            call_data['DetailLevel'] = 'ReturnAll'
            error_msg = 'Get the category features for %s' % category.category_id
            api = ebay_ebay_obj.call(cr, uid, user, 'GetCategoryFeatures', call_data, error_msg, context=context)
            resp_dict = api.response_dict()
            category_feature = resp_dict.Category
            vals = dict()
            if category_feature.has_key('ConditionEnabled'):
                vals['condition_enabled'] = category_feature.ConditionEnabled
                readability = "%s | %s\n" % ("DisplayName", "ID")
                readability += "%s\n" % ("-" * 64,)
                for condition in category_feature.ConditionValues.Condition:
                    readability += "%s | %s\n" % (condition.DisplayName, condition.ID)
                vals['condition_values'] = readability
            vals['free_gallery_plus_enabled'] = category_feature.get('FreeGalleryPlusEnabled', 'false') == 'true'
            vals['free_picture_pack_enabled'] = category_feature.get('FreePicturePackEnabled', 'false') == 'true'
            vals['handling_time_enabled'] = category_feature.get('HandlingTimeEnabled', 'false') == 'true'
            vals['item_specifics_enabled'] = category_feature.get('ItemSpecificsEnabled', '')
            vals['variations_enabled'] = category_feature.get('VariationsEnabled', 'false') == 'true'
            vals['category_feature'] = api.response.content
            category.write(vals)
    
ebay_category()

class ebay_buyerrequirementdetails(osv.osv):
    _name = "ebay.buyerrequirementdetails"
    _description = "eBay buyer requirement details"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'linked_paypal_account': fields.boolean('LinkedPayPalAccount'),
        # MaximumBuyerPolicyViolations
        'mbpv_count': fields.integer('Count'),
        'mbpv_period': fields.selection([
            ('Days_30', '30 days'),
            ('Days_180', '180 days'),
            ],'Period'),
        # MaximumItemRequirements
        'mir_maximum_item_count': fields.integer('MaximumItemCount', help='As of Jan. 2013, the valid values for the US site are: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 25, 50, and 75.'),
        'mir_minimum_feedback_score': fields.integer('MinimumFeedbackScore', help='Currently, the valid values for the US site are: 0, 1, 2, 3, 4, and 5.'),
        # MaximumUnpaidItemStrikesInfo
        'muisi_count': fields.integer('Count'),
        'muisi_period': fields.selection([
            ('Days_30', '30 days'),
            ('Days_180', '180 days'),
            ('Days_360', '360 days'),
            ],'Period'),
        'minimum_feedback_score': fields.integer('MinimumFeedbackScore'),
        'ship2registration_country': fields.boolean('ShipToRegistrationCountry'),
        # VerifiedUserRequirements
        'vur_minimum_feedback_score': fields.integer('MinimumFeedbackScore'),
        'vur_verified_user': fields.boolean('VerifiedUser'),
        'zero_feedback_score': fields.boolean('ZeroFeedbackScore'),
        'ebay_item_ids': fields.one2many('ebay.item', 'buyer_requirement_details_id', 'Item'),
    }
    
    _defaults = {
        'linked_paypal_account': False,
        'mbpv_count': 4,
        'mbpv_period': 'Days_180',
        'mir_maximum_item_count': 5,
        'mir_minimum_feedback_score': 5,
        'muisi_count': 2,
        'muisi_period': 'Days_30',
        'minimum_feedback_score': -1,
        'ship2registration_country': True,
        'vur_minimum_feedback_score': 5,
        'vur_verified_user': True,
        'zero_feedback_score': False,
    }
    
    def dict(self, cr, uid, ids, user, this, context=None):
        buyer_requirement_details = dict(
            LinkedPayPalAccount="true" if this.linked_paypal_account else "false",
            MinimumFeedbackScore=this.minimum_feedback_score,
            ShipToRegistrationCountry="true" if this.ship2registration_country else "false",
        )
        
        buyer_requirement_details['MaximumBuyerPolicyViolations'] = dict(
            Count=this.mbpv_count,
            Period=this.mbpv_period,
        )
        
        buyer_requirement_details['MaximumItemRequirements'] = dict(
            MaximumItemCount=this.mir_maximum_item_count,
        )
        if this.mir_minimum_feedback_score:
            buyer_requirement_details['MaximumItemRequirements']['MinimumFeedbackScore'] = this.mir_minimum_feedback_score
        
        buyer_requirement_details['MaximumUnpaidItemStrikesInfo'] = dict(
            Count=this.muisi_count,
            Period=this.muisi_period,
        )
        '''
        buyer_requirement_details['VerifiedUserRequirements'] = dict(
            MinimumFeedbackScore=this.vur_minimum_feedback_score,
            VerifiedUser=this.vur_verified_user,
        )
        '''
        
        return buyer_requirement_details
    
ebay_buyerrequirementdetails()
    
class ebay_conditiondescription(osv.osv):
    _name = "ebay.conditiondescription"
    _description = "eBay condition description"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'description': fields.text('Description', size=1000, required=True),
        'ebay_item_ids': fields.one2many('ebay.item', 'condition_description_id', 'Item'),
    }
    
    _defaults = {
    }
    
ebay_conditiondescription()

class ebay_eps_picturesetmember(osv.osv):
    _name = "ebay.eps.picturesetmember"
    _description = "eBay EPS Picture"
    
    _columns = {
        'member_url': fields.char('URL'),
        'picture_height': fields.integer('Height'),
        'picture_width': fields.integer('Width'),
        'ebay_eps_picture_id': fields.many2one('ebay.eps.picture', 'EPS Picture', ondelete='cascade'),
    }
    
    _rec_name = 'member_url'

ebay_eps_picturesetmember()

class ebay_eps_picture(osv.osv):
    _name = "ebay.eps.picture"
    _description = "eBay EPS Picture"
    
    def _get_image(self, cr, uid, ids, name, args, context=None):
        result = dict.fromkeys(ids, False)
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = tools.image_get_resized_images(obj.image)
        return result
    
    def _set_image(self, cr, uid, id, name, value, args, context=None):
        return self.write(cr, uid, [id], {'image': tools.image_resize_image_big(value)}, context=context)
    
    def _has_image(self, cr, uid, ids, name, args, context=None):
        result = {}
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = obj.image != False
        return result
    
    _columns = {
        'name': fields.char('Name', required=True),
        'dummy': fields.boolean('Dummy', help="This a dummy picture for optimize speed sync seller active item, you must sync picture to fecth the real image"),
        # image: all image fields are base64 encoded and PIL-supported
        'image': fields.binary("Image", required=True,
            help="This field holds the image used as avatar for this contact, limited to 1024x1024px"),
        'image_medium': fields.function(_get_image, fnct_inv=_set_image,
            string="Medium-sized image", type="binary", multi="_get_image",
            store={
                'ebay.eps.picture': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Medium-sized image of this contact. It is automatically "\
                 "resized as a 128x128px image, with aspect ratio preserved. "\
                 "Use this field in form views or some kanban views."),
        'image_small': fields.function(_get_image, fnct_inv=_set_image,
            string="Small-sized image", type="binary", multi="_get_image",
            store={
                'ebay.eps.picture': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Small-sized image of this contact. It is automatically "\
                 "resized as a 64x64px image, with aspect ratio preserved. "\
                 "Use this field anywhere a small image is required."),
        'has_image': fields.function(_has_image, type="boolean"),
        # SiteHostedPictureDetails
        'base_url': fields.char('BaseURL', readonly=True),
        'external_picture_url ': fields.char('ExternalPictureURL', readonly=True),
        'full_url': fields.char('FullURL', readonly=True),
        'picture_format': fields.char('PictureFormat', readonly=True),
        'picturesetmember_ids': fields.one2many('ebay.eps.picturesetmember', 'ebay_eps_picture_id', 'PictureSetMember', readonly=True),
        'use_by_date': fields.datetime('UseByDate', readonly=True),
        'ebay_item_id': fields.many2one('ebay.item', 'Item', readonly=True, ondelete='cascade'),
    }
    
    _defaults = {
        'dummy': False
    }
    
    _order = 'name'
    
    def write(self, cr, uid, ids, vals, context=None):
        if context is None:
            context = {}
        if not ids:
            return True
        if 'image' in vals:
            vals['dummy'] = False
            vals['use_by_date'] = fields.datetime.now()
        return super(ebay_eps_picture, self).write(cr, uid, ids, vals, context=context)
    
    def upload(self, cr, uid, ids, item, picture, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_eps_picturesetmember = self.pool.get('ebay.eps.picturesetmember')
        user = item.ebay_user_id
        active = item.state == 'Active'
        
        now = datetime.now()
        
        if not picture.use_by_date or (((ebay_strptime(picture.use_by_date) - now).days < 2) and (active != True)):
            image = io.BytesIO(base64.b64decode(picture.image))
            call_data = dict()
            call_data['PictureSet'] = 'Supersize'
            call_data['PictureSystemVersion'] = 2
            #call_data['PictureUploadPolicy'] = 'Add'
            
            call_name = 'UploadSiteHostedPictures'
            api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
            api.execute(call_name, call_data, files=dict(image=image))
            reply = api.response.reply
            site_hosted_picture_details = reply.SiteHostedPictureDetails
            vals = dict()
            vals['base_url'] = site_hosted_picture_details.BaseURL
            #vals['external_picture_url'] = site_hosted_picture_details.ExternalPictureURL
            vals['full_url'] = site_hosted_picture_details.FullURL
            vals['picture_format'] = site_hosted_picture_details.PictureFormat
            vals['use_by_date'] = site_hosted_picture_details.UseByDate
            picture.write(vals)
            picture.refresh()
            picture_set_member = site_hosted_picture_details.PictureSetMember
            cr.execute('delete from ebay_eps_picturesetmember where ebay_eps_picture_id=%s', (picture.id,))
            for picture_set in picture_set_member:
                vals = dict()
                vals['member_url'] = picture_set.MemberURL
                vals['picture_height'] = picture_set.PictureHeight
                vals['picture_width'] = picture_set.PictureWidth
                vals['ebay_eps_picture_id'] = picture.id
                ebay_eps_picturesetmember.create(cr, uid, vals, context=context)
    
ebay_eps_picture()

class ebay_returnpolicy(osv.osv):
    _name = "ebay.returnpolicy"
    _description = "eBay return policy"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'description': fields.text('Description', size=5000),
        'refund_option': fields.selection([
            ('MoneyBack', 'Money Back'),
            ('MoneyBackOrReplacement', 'Money back or replacement'),
            ('MoneyBackOrExchange', 'Money back or exchange'),
            ], 'RefundOption', required=True),
        'restocking_feevalue_option': fields.char('RestockingFeeValueOption'),
        'returns_accepted_option': fields.selection([
            ('ReturnsAccepted', 'Returns Accepted'),
            ('ReturnsNotAccepted', 'No returns accepted'),
            ], 'ReturnsAcceptedOption', required=True),
        'returns_within_option':  fields.selection([
            ('Days_14', '14 Days'),
            ('Days_30', '30 Days'),
            ('Days_60', '60 Days'),
            ], 'ReturnsWithinOption', required=True),
        'shipping_cost_paid_by_option':  fields.selection([
            ('Buyer', 'Buyer'),
            ('Seller', 'Seller'),
            ], 'ShippingCostPaidByOption', required=True),
        'warranty_duration_option': fields.char('WarrantyDurationOption'),
        'warranty_offered_option': fields.char('WarrantyOfferedOption'),
        'warranty_type_option': fields.char('WarrantyTypeOption'),
        'ebay_item_ids': fields.one2many('ebay.item', 'return_policy_id', 'Item'),
    }

    _defaults = {
    }
    
    def dict(self, cr, uid, ids, user, this, context=None):
        return_policy = dict(
            RefundOption=this.refund_option,
            ReturnsAcceptedOption=this.returns_accepted_option,
            ReturnsWithinOption=this.returns_within_option,
            ShippingCostPaidByOption=this.shipping_cost_paid_by_option,
        )
        if this.description:
            return_policy['description'] = '<![CDATA[' + this.description + ']]>'
        return return_policy
    
ebay_returnpolicy()

class ebay_shippingdetails(osv.osv):
    _name = "ebay.shippingdetails"
    _description = "eBay shipping details"
    
    _columns = {
        'name': fields.char('Name', required=True),
        'exclude_ship_to_location': fields.text('Exclude Ship To Location'),
        # InternationalShippingServiceOption
        # Shipping costs and options related to an international shipping service.
        'isso_shipping_service': fields.char('Shipping Service', required=True),
        'isso_shipping_service_additional_cost': fields.float('Additional Cost'),
        'isso_shipping_service_cost': fields.float('Cost'),
        'isso_shipping_service_priority': fields.integer('ShippingServicePriority'),
        # ShippingServiceOptions
        # Shipping costs and options related to domestic shipping services offered by the seller.
        # Flat and calculated shipping.
        'sso_free_shipping': fields.boolean('Free Shipping'),
        'sso_shipping_service': fields.char('Shipping Service', required=True),
        'sso_shipping_service_additional_Cost': fields.float('Additional Cost'),
        'sso_shipping_service_cost': fields.float('Cost'),
        'sso_shipping_service_priority': fields.integer('ShippingServicePriority'),
        'shipping_type': fields.selection([
            ('Calculated', 'Calculated'),
            ('CalculatedDomesticFlatInternational', 'CalculatedDomesticFlatInternational'),
            ('CustomCode', 'CustomCode'),
            ('Flat', 'Flat'),
            ('FlatDomesticCalculatedInternational', 'FlatDomesticCalculatedInternational'),
            ('FreightFlat', 'FreightFlat'),
            ('NotSpecified', 'NotSpecified'),
        ], 'ShippingType', readonly=True),
        'ebay_item_ids': fields.one2many('ebay.item', 'shipping_details_id', 'Item'),
    }
    
    _defaults = {
        'isso_shipping_service': 'OtherInternational',
        'isso_shipping_service_additional_cost': 0.0,
        'isso_shipping_service_cost': 0.0,
        'isso_shipping_service_priority': 1,
        'sso_free_shipping': True,
        'sso_shipping_service': 'EconomyShippingFromOutsideUS',
        'sso_shipping_service_additional_Cost': 0.0,
        'sso_shipping_service_cost': 0.0,
        'sso_shipping_service_priority': 1,
        'shipping_type': 'Flat',
    }
    
    def on_change_sso_free_shipping(self, cr, uid, id, sso_free_shipping, context=None):
        if sso_free_shipping:
            return {
                'value': {
                    'sso_shipping_service_cost': 0.0,
                    'sso_shipping_service_additional_Cost': 0.0,
                }
            }
        else:
            return {
                'value': {
                }
            }
        
    def dict(self, cr, uid, ids, user, this, context=None):
        shipping_details = dict()
        shipping_details['InternationalShippingServiceOption'] = dict(
            ShippingService=this.isso_shipping_service,
            ShippingServiceAdditionalCost=this.sso_shipping_service_additional_Cost,
            ShippingServiceCost=this.isso_shipping_service_cost,
            ShippingServicePriority=this.isso_shipping_service_priority,
            ShipToLocation='Worldwide'
        )
        
        exclude_ship_to_location = user.exclude_ship_to_location
        if exclude_ship_to_location:
            shipping_details['ExcludeShipToLocation'] = user.exclude_ship_to_location.split('|')
        
        shipping_details['ShippingServiceOptions'] = dict(
            ShippingService=this.sso_shipping_service,
            ShippingServicePriority=this.sso_shipping_service_priority,
        )
        if this.sso_free_shipping:
            shipping_details['ShippingServiceOptions']['FreeShipping'] = "true"
        else:
            shipping_details['ShippingServiceOptions']['ShippingServiceAdditionalCost'] = this.sso_shipping_service_additional_Cost
            shipping_details['ShippingServiceOptions']['ShippingServiceCost'] = this.sso_shipping_service_cost

        shipping_details['ShippingType'] = this.shipping_type
        return shipping_details
    
ebay_shippingdetails()

class ebay_product(osv.osv):
    _name = "ebay.product"
    _description = "eBay product"
    
    _columns = {
        'product_id': fields.many2one('product.product', 'Product', required=True, ondelete='no action'),
        'uos_coeff': fields.float('Unit of Sale Coeff', digits_compute= dp.get_precision('Product UoS'), required=True),
        'ebay_item_id': fields.many2one('ebay.item', 'eBay Item', ondelete='cascade'),
    }
    
    _defaults = {
        'uos_coeff': 1.0
    }

def split_str(s, sep):
    if not s:
        return list()
    if sep == '\n':
        s_list = s.splitlines()
    else:
        s_list = s.split(sep)
    d = list()
    for l in s_list:
        d.append(l.strip())
    return d

class ebay_item_category(osv.osv):

    def name_get(self, cr, uid, ids, context=None):
        """Return the categories' display name, including their direct
           parent by default.

        :param dict context: the ``partner_category_display`` key can be
                             used to select the short version of the
                             category name (without the direct parent),
                             when set to ``'short'``. The default is
                             the long version."""
        if context is None:
            context = {}
        if context.get('partner_category_display') == 'short':
            return super(ebay_item_category, self).name_get(cr, uid, ids, context=context)
        if isinstance(ids, (int, long)):
            ids = [ids]
        reads = self.read(cr, uid, ids, ['name', 'parent_id'], context=context)
        res = []
        for record in reads:
            name = record['name']
            if record['parent_id']:
                name = record['parent_id'][1] + ' / ' + name
            res.append((record['id'], name))
        return res

    def name_search(self, cr, uid, name, args=None, operator='ilike', context=None, limit=100):
        if not args:
            args = []
        if not context:
            context = {}
        if name:
            # Be sure name_search is symetric to name_get
            name = name.split(' / ')[-1]
            ids = self.search(cr, uid, [('name', operator, name)] + args, limit=limit, context=context)
        else:
            ids = self.search(cr, uid, args, limit=limit, context=context)
        return self.name_get(cr, uid, ids, context)


    def _name_get_fnc(self, cr, uid, ids, prop, unknow_none, context=None):
        res = self.name_get(cr, uid, ids, context=context)
        return dict(res)

    _description = 'eBay Item Categories'
    _name = 'ebay.item.category'
    _columns = {
        'name': fields.char('Category Name', required=True, size=64, translate=True),
        'parent_id': fields.many2one('ebay.item.category', 'Parent Category', select=True, ondelete='cascade'),
        'complete_name': fields.function(_name_get_fnc, type="char", string='Full Name'),
        'child_ids': fields.one2many('ebay.item.category', 'parent_id', 'Child Categories'),
        'active': fields.boolean('Active', help="The active field allows you to hide the category without removing it."),
        'parent_left': fields.integer('Left parent', select=True),
        'parent_right': fields.integer('Right parent', select=True),
        'ebay_item_ids': fields.many2many('ebay.item', id1='ebay_item_category_id', id2='ebay_item_id', string='eBay Items'),
    }
    _constraints = [
        (osv.osv._check_recursion, 'Error ! You can not create recursive categories.', ['parent_id'])
    ]
    _defaults = {
        'active': 1,
    }
    _parent_store = True
    _parent_order = 'name'
    _order = 'parent_left'
    
ebay_item_category()

class ebay_item(osv.osv):
    _name = "ebay.item"
    _description = "eBay item"
    
    def _get_item_view_url(self, cr, uid, ids, field_name, arg, context):
        if context is None:
            context = {}
        res = dict.fromkeys(ids, False)
        for record in self.browse(cr, uid, ids, context=context):
            if record.item_id:
                if record.ebay_user_id.sandbox:
                    res[record.id] = "http://cgi.sandbox.ebay.com/ws/eBayISAPI.dll?ViewItem&item=%s" % record.item_id
                else:
                    res[record.id] = "http://cgi.ebay.com/ws/eBayISAPI.dll?ViewItem&item=%s" % record.item_id
        return res
    
    def _get_image(self, cr, uid, ids, name, args, context=None):
        result = dict.fromkeys(ids, False)
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = obj.eps_picture_ids[0][name]
        return result
    
    def _has_image(self, cr, uid, ids, name, args, context=None):
        result = {}
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = obj.eps_picture_ids != False
        return result
    
    _columns = {
        #'auto_pay': fields.boolean('AutoPay'),
        'buyer_requirement_details_id': fields.many2one('ebay.buyerrequirementdetails', 'Buyer Requirement', ondelete='set null'),
        'buy_it_now_price': fields.float('BuyItNowPrice'),
        'condition_description_id': fields.many2one('ebay.conditiondescription', 'Condition Description', ondelete='set null'),
        'condition_id': fields.integer('Condition ID'),
        'country': fields.char('Country', size=2),
        'cross_border_trade': fields.char('CrossBorderTrade'),
        'currency': fields.char('Currency', size=3),
        'description': fields.html('Description'),
        'disable_buyer_requirements': fields.boolean('DisableBuyerRequirements'),
        'dispatch_time_max': fields.integer('DispatchTimeMax'),
        'hit_counter': fields.selection([
            ('BasicStyle', 'BasicStyle'),
            ('CustomCode', 'CustomCode'),
            ('GreenLED', 'GreenLED'),
            ('Hidden', 'Hidden'),
            ('HiddenStyle', 'HiddenStyle'),
            ('HonestyStyle', 'HonestyStyle'),
            ('NoHitCounter', 'NoHitCounter'),
            ('RetroStyle', 'RetroStyle'),
        ], 'HitCounter'),
        'include_recommendations': fields.boolean('IncludeRecommendations'),
        'item_specifics': fields.text('ItemSpecifics', help="""
For example:
    Name1=Value1
    Name2=Value2
    Name3=Value3
        """),
        'listing_duration': fields.selection([
            ('Days_1', '1 days'),
            ('Days_3', '3 days'),
            ('Days_5', '5 days'),
            ('Days_7', '7 days'),
            ('Days_10', '10 days'),
            ('Days_30', '30 days'),
            ('GTC', 'GTC'),
            ],'Duration', help='''
1 days (only for Auction)
30 days (only for Fixed Price)
GTC (only for Fixed Price)
            '''),
        'listing_type': fields.selection([
            #('AdType', 'AdType'),
            ('Chinese', 'Auction'),
            ('German', 'Auction/ Best Offer'),
            #('CustomCode', 'CustomCode'),
            ('FixedPriceItem', 'Fixed Price'),
            #('Half', 'Half'),
            #('LeadGeneration', 'LeadGeneration'),
        ], 'Format', required=True),
        'location': fields.char('Location'),
        'out_of_stock_control': fields.boolean('OutOfStockControl'),
        'payment_methods': fields.char('PaymentMethods'),
        'paypal_email_address': fields.char('PayPalEmailAddress'),
        'payment_methods': fields.char('PaymentMethods'),
        #PictureDetails
        'eps_picture_ids': fields.one2many('ebay.eps.picture', 'ebay_item_id', 'Picture'),
        'postal_code': fields.char('PostalCode'),
        'primary_category_id': fields.many2one('ebay.category', 'Category', ondelete='set null'),
        'quantity': fields.integer('Quantity', required=True),
        'return_policy_id': fields.many2one('ebay.returnpolicy', 'Return Policy', ondelete='set null'),
        'schedule_time': fields.datetime('ScheduleTime'),
        'secondary_category_id': fields.many2one('ebay.category', '2nd Category', ondelete='set null'),
        'shipping_details_id': fields.many2one('ebay.shippingdetails', 'Shipping Details', ondelete='set null'),
        'shipping_terms_in_description': fields.boolean('ShippingTermsInDescription'),
        'site': fields.char('Site', size=16),
        'start_price': fields.float('StartPrice', required=True),
        # Storefront
        'store_category2id': fields.integer('2nd Store Category'),
        'store_category2name': fields.char('2nd Store Category'),
        'store_category_id': fields.integer('Store Category'),
        'store_category_name': fields.char('Store Category'),
        'subtitle': fields.char('SubTitle', size=55),
        'name': fields.char('Title', required=True, select=True),
        'uuid': fields.char('UUID', size=32),
        # Variations
        'variation_invalid': fields.boolean('Variation Invalid'),
        'variation': fields.boolean('Variation'),
        'variation_modify_specific_name': fields.text('Modify Name', help='''
oldname1 | newname1
oldname2 | newname2
...
        '''),
        'variation_specific_name': fields.char('Names', help='Primary name | Secondary name ...'),
        'variation_specifics_set': fields.text('Values', help='''
Primary value1 | Primary value2 ...
Secondary value1 | Secondary value2 ...
        '''),
        'parent_id': fields.many2one('ebay.item', 'Parent Item', select=True, ondelete='cascade'),
        'child_ids': fields.one2many('ebay.item', 'parent_id', 'Child Item'),
        'variation_deleted': fields.boolean('Delete'),
        # SKU
        'product_ids': fields.one2many('ebay.product', 'ebay_item_id', 'Product'),
        # Item Status ------------
        'bid_count': fields.integer('Bit Count', readonly=True),
        'end_time': fields.datetime('End Time', readonly=True),
        'hit_count': fields.integer('Hit Count', readonly=True),
        'item_id': fields.char('Item ID', size=38),
        'quantity_sold': fields.integer('Sold', readonly=True),
        'quantity_surplus': fields.integer('Surplus', readonly=True),
        'start_time': fields.datetime('Start Time', readonly=True),
        'state': fields.selection([
            ('Draft', 'Draft'),
            ('Active', 'Active'),
            ('Completed', 'Completed'),
            ('Ended', 'Ended'),
        ], 'Status', readonly=True),
        'time_left': fields.char('Time Left', readonly=True),
        'need_to_be_updated': fields.boolean('Need to be updated'),
        'revise_date': fields.datetime('Revise Date', readonly=True),
        'update_date': fields.datetime('Update Date', readonly=True),
        'view_item_url': fields.function(_get_item_view_url, type='char', method=True, string='View Item'),
        'watch_count': fields.integer('Watch Count', readonly=True),
        'severity_code_error': fields.boolean('Severity Code Error', readonly=True),
        'severity_code_warning': fields.boolean('Severity Code Warning', readonly=True),
        'error_message': fields.html('Error Message', readonly=True),
        'response': fields.text('Response', readonly=True),
        # Additional Info
        'description_tmpl_id': fields.many2one('ebay.item.description.template', 'Template', ondelete='set null'),
        'site': fields.selection([
            ('US', 'US'),
            ('Germany', 'Germany',),
            ('Canada', 'Canada',),
            ('UK', 'UK'),
            ('Australia', 'Australia'),
            ('HongKong', 'HongKong'),
        ], 'Site', required=True),
        'ebay_user_id': fields.many2one('ebay.user', 'Account', domain=[('ownership','=',True)], ondelete='set null'),
        'ebay_item_category_id': fields.many2many('ebay.item.category', id1='ebay_item_id', id2='ebay_item_category_id', string='Tags'),
        'image': fields.function(_get_image, type="binary", method=True, string='Image'),
        'has_image': fields.function(_has_image, type="boolean"),
    }
    
    def _get_default_buyer_requirement_details_id(self, cr, uid, context=None):
        res = self.pool.get('ebay.buyerrequirementdetails').search(cr, uid, [], context=context)
        return res and res[0] or False
    
    def _get_default_return_policy_id(self, cr, uid, context=None):
        res = self.pool.get('ebay.returnpolicy').search(cr, uid, [], context=context)
        return res and res[0] or False
    
    def _get_default_shipping_details_id(self, cr, uid, context=None):
        res = self.pool.get('ebay.shippingdetails').search(cr, uid, [], context=context)
        return res and res[0] or False
    
    def _get_default_description_tmpl_id(self, cr, uid, context=None):
        res = self.pool.get('ebay.item.description.template').search(cr, uid, [], context=context)
        return res and res[0] or False
    
    
    def _default_ebay_item_category(self, cr, uid, context=None):
        if context is None:
            context = {}
        if context.get('ebay_item_category_id'):
            return [context['ebay_item_category_id']]
        return False
    
    _defaults = {
        'buyer_requirement_details_id': _get_default_buyer_requirement_details_id,
        'buy_it_now_price': 19.99,
        'condition_id': 1000,
        'cross_border_trade': 'North America',
        'country': 'DE',
        'currency': 'EUR',
        'disable_buyer_requirements': False,
        'dispatch_time_max': 2,
        'hit_counter': 'HiddenStyle',
        'include_recommendations': True,
        'listing_duration': 'GTC',
        'listing_type': 'FixedPriceItem',
        'location': 'Reutlingen',
        'quantity': 99,
        'return_policy_id': _get_default_return_policy_id,
        'shipping_details_id': _get_default_shipping_details_id,
        'uuid': lambda self, cr, uid, context: uuid.uuid1().hex,
        'variation_invalid': True,
        'variation_deleted': False,
        'start_price': 9.99,
        'state': 'Draft',
        'need_to_be_updated': True,
        'site': 'DE',
        'description_tmpl_id': _get_default_description_tmpl_id,
        'ebay_item_category_id': _default_ebay_item_category,
    }
    
    def on_change_primary_category_id(self, cr, uid, id, primary_category_id, listing_type, context=None):
        if not primary_category_id:
            return False
        value = dict()
        variation_invalid = False
        category = self.pool.get('ebay.category').browse(cr, uid, primary_category_id, context=context)
        if listing_type == 'German':
            value['quantity'] = 1
            value['listing_duration'] = 'Days_3'
        else:
            value['quantity'] = 99
            value['listing_duration'] = 'GTC'
        if listing_type == 'German' or not category.variations_enabled:
            value['variation_invalid'] = True
            value['variation'] = False
        else:
            value['variation_invalid'] = False
            value['variation'] = False
        return {
            'value': value
        }
    
    def on_change_listing_type(self, cr, uid, id, primary_category_id, listing_type, context=None):
        return self.on_change_primary_category_id(cr, uid, id, primary_category_id, listing_type, context=context)
    
    def on_change_variation_specifics_set(self, cr, uid, id, variation_specifics_set, context=None):
        value = dict()
        specifics_set = split_str(variation_specifics_set, '\n')
        value['name'] = '[%s]' % ']['.join(specifics_set)
        return {
            'value': value
        }
    
    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        
        name = self.read(cr, uid, id, ['name'], context=context)['name']
        default = default.copy()
        default.update({
            'name': name + _(' (Copy)'),
            'item_id': '',
            'state': 'Draft',
            'need_to_be_updated': True,
            'uuid': uuid.uuid1().hex,
            'severity_code_error': False,
            'severity_code_warning': False,
            'error_message': '',
        })

        return super(ebay_item, self).copy(cr, uid, id, default, context)
    
    def unlink(self, cr, uid, ids, context=None, check=True):
        if check:
            for item in self.browse(cr, uid, ids, context=context):
                if not item.parent_id or item.state != 'Active':
                    item.unlink(check=False)
                else:
                    item.write(dict(variation_deleted=True))
        else:
            return super(ebay_item, self).unlink(cr, uid, ids, context=context)
        
        return True
    
    def write(self, cr, uid, ids, vals, context=None):
        if context is None:
            context = {}
        if not ids:
            return True
        keywords = set([
            'buyer_requirement_details_id',
            'buy_it_now_price',
            'condition_description_id',
            'condition_id',
            'country',
            'cross_border_trade',
            'currency',
            'description',
            'disable_buyer_requirements',
            'dispatch_time_max',
            'hit_counter',
            'item_specifics',
            'listing_duration',
            'listing_type',
            'location',
            'out_of_stock_control',
            'payment_methods',
            'paypal_email_address',
            'payment_methods',
            'eps_picture_ids',
            'postal_code',
            'primary_category_id',
            'quantity',
            'return_policy_id',
            'schedule_time',
            'secondary_category_id',
            'shipping_details_id',
            'shipping_terms_in_description',
            'site',
            'start_price',
            'store_category2id',
            'store_category2name',
            'store_category_id',
            'store_category_name',
            'subtitle',
            'name',
            'uuid',
            'variation_specifics_set',
            'variation_deleted',
            'child_ids',
        ])
        if len(keywords & set(vals.keys())) > 0 or vals.get('variation_modify_specific_name', ''):
            vals['need_to_be_updated'] = True
        state = vals.get('state')
        if state in ('Completed', 'Ended'):
            vals['uuid'] = uuid.uuid1().hex
        return super(ebay_item, self).write(cr, uid, ids, vals, context=context)
    
    def item_variation_dict(self, cr, uid, ids, item, item_dict, context=None): 
        if not item.child_ids:
            return True
                
        user = item.ebay_user_id
        item_dict['Item']['Variations'] = dict()
        specific_names = split_str(item.variation_specific_name, '|')
        
        pictures = dict()
        variants = list()
        for variant in item.child_ids:
            index = 0
            name_value_list = list()
            for value in split_str(variant.variation_specifics_set, '\n'):
                name_value_list.append(dict(
                    Name=specific_names[index],
                    Value=value,
                ))
                index+=1
            v = dict(
                    Quantity=variant.quantity,
                    SKU=variant.id,
                    StartPrice=variant.start_price,
                    VariationSpecifics=dict(
                        NameValueList=name_value_list if len(name_value_list) > 1 else name_value_list[0],
                    )
                )
            
            if variant.eps_picture_ids:
                specific_value = name_value_list[0]['Value']
                for _pic in variant.eps_picture_ids:
                    if not pictures.has_key(specific_value):
                        pictures[specific_value] = list()
                    pictures[specific_value].append(_pic.full_url)
            
            if variant.variation_deleted:
                if variant.quantity_sold > 0:
                    v['Quantity'] = 0
                else:
                    v['Delete'] = 'true'
            variants.append(v)
            
        item_dict['Item']['Variations']['Variation'] = variants if len(variants) > 1 else variants[0]
        
        if pictures:
            picture_set = dict(
                VariationSpecificName=specific_names[0],
                VariationSpecificPictureSet=dict()
            )
            variation_specific_picture_set = list()
            for key, value in pictures.items():
                variation_specific_picture_set.append(dict(
                    PictureURL=value if len(value) > 1 else value[0],
                    VariationSpecificValue=key,
                ))
            picture_set['VariationSpecificPictureSet'] = variation_specific_picture_set \
                if len(variation_specific_picture_set) > 1 \
                else variation_specific_picture_set[0]
            item_dict['Item']['Variations']['Pictures'] = picture_set
            
        name_value_list = list()
        index = 0
        for specific_values in split_str(item.variation_specifics_set, '\n'):
            if specific_values:
                specific_values = split_str(specific_values, '|')
                name_value_list.append(dict(
                    Name=specific_names[index],
                    Value=specific_values if len(specific_values) > 1 else specific_values[0]
                ))
                index+=1
        item_dict['Item']['Variations']['VariationSpecificsSet'] = dict(
            NameValueList=name_value_list if len(name_value_list) > 1 else name_value_list[0]
        )
        
        return True
    
    def item_create(self, cr, uid, item, context=None):
        user = item.ebay_user_id
        auction = item.listing_type == 'German'
        
        if item.description_tmpl_id and item.description_tmpl_id.template:
            template = Template(item.description_tmpl_id.template)
            description = template.render(
                member_id=user.name,
                gallery=list(),
                description=item.description,
                sku=base64.b64encode(str(item.id)),
            ).replace('\r', '').replace('\n', '').replace('\t', '')
        else:
            description = item.description
            
        item_dict = {
            'Item': {
                'CategoryMappingAllowed': 'true',
                "ConditionID": item.condition_id,
                'Country': user.country,
                'Currency': item.currency,
                'Description': '<![CDATA[' + description + ']]>',
                'DispatchTimeMax': item.dispatch_time_max,
                'HitCounter': item.hit_counter,
                'ListingDuration': item.listing_duration,
                'Location': user.location,
                'PaymentMethods': 'PayPal',
                'PayPalEmailAddress': user.paypal_email_address,
                'PrimaryCategory': dict(CategoryID=item.primary_category_id.category_id),
                'Quantity': item.quantity,
                'Site': item.site,
                'SKU': item.id,
                'StartPrice': item.start_price,
                'Title': '<![CDATA[' + item.name + ']]>',
                'UUID': item.uuid,
            }
        }
        
        if item.eps_picture_ids:
            picture_url = list()
            for picture in item.eps_picture_ids:
                picture_url.append(picture.full_url)
            else:
                if len(picture_url) == 1:
                    item_dict['Item']['PictureDetails'] = dict(
                        GalleryType='Gallery',
                        PhotoDisplay='SuperSize',
                        PictureSource='EPS',
                        PictureURL=picture_url[0],
                    )
                elif len(picture_url) > 1:
                    item_dict['Item']['PictureDetails'] = dict(
                        GalleryType='Gallery',
                        PhotoDisplay='SuperSize',
                        PictureSource='EPS',
                        PictureURL=picture_url,
                    )
        
        if auction:
            if item.buy_it_now_price:
                #item_dict['Item']['AutoPay'] = 'true'
                item_dict['Item']['BuyItNowPrice'] = item.buy_it_now_price
        else:
            #item_dict['Item']['AutoPay'] = 'true'
            item_dict['Item']['OutOfStockControl'] = 'true'
            # Variations
            if not item.variation_invalid and item.variation:
                del item_dict['Item']['Quantity']
                del item_dict['Item']['StartPrice']
                item.item_variation_dict(item, item_dict)
        
        if item.buyer_requirement_details_id:
            item_dict['Item']['BuyerRequirementDetails'] = item.buyer_requirement_details_id.dict(user, item.buyer_requirement_details_id)
            
        if item.return_policy_id:
            item_dict['Item']['ReturnPolicy'] = item.return_policy_id.dict(user, item.return_policy_id)
        
        if item.shipping_details_id:
            item_dict['Item']['ShippingDetails'] = item.shipping_details_id.dict(user, item.shipping_details_id)
        
        return item_dict, auction
    
    def item_revise(self, cr, uid, item, context=None):
        item_dict, auction = self.item_create(cr, uid, item, context=context)
        item_dict['Item']['DescriptionReviseMode'] = 'Replace'
        item_dict['Item']['ItemID'] = item.item_id
        if item.bid_count > 0 or item.quantity_sold > 0:
            del item_dict['Item']['ListingDuration']
            del item_dict['Item']['PrimaryCategory']
            #del item_dict['Item']['Title']
        return item_dict, auction
    
    def item_post_update(self, cr, uid, item, context=None):
        def eps_picture_extend_use_by_date(item):
            eps_picture = item.eps_picture_ids
            if eps_picture:
                for picture in eps_picture:
                    if picture.full_url:
                        picture.write(dict(use_by_date=(datetime.now() + timedelta(90))))
        
        item.refresh()
        eps_picture_extend_use_by_date(item)
        
        varations = item.child_ids
        if varations:
            for varation in varations:
                eps_picture_extend_use_by_date(varation)
                varation.write({'need_to_be_updated': False, 'state': item.state})
            
        return True
        
    def picture_upload(self, cr, uid, item, context=None):
        try:
            user = item.ebay_user_id
            if item.eps_picture_ids:
                for picture in item.eps_picture_ids:
                    picture.upload(item, picture)
                    
            if not item.variation_invalid and item.variation and item.child_ids:
                for child in item.child_ids:
                    if child.eps_picture_ids:
                        for picture in child.eps_picture_ids:
                            picture.upload(item, picture)
        except ConnectionError as e:
            vals = dict()
            vals['severity_code_error'] = True
            vals['severity_code_warning'] = False
            vals['error_message'] = e
            item.write(vals)
            return False
        else:
            return True
        
    def item_upload(self, cr, uid, ids, item, context=None):
        if item.state not in ('Draft', 'Completed', 'Ended'):
            return
        
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        user = item.ebay_user_id
        
        if self.picture_upload(cr, uid, item, context=context) == False:
            return
        
        call_data, auction = self.item_create(cr, uid, item, context=context)
        
        if item.item_id:
            call_data['Item']['ItemID'] = item.item_id
            call_name = "RelistItem" if auction else "RelistFixedPriceItem"
        else:
            call_name = "AddItem" if auction else "AddFixedPriceItem"
        
        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
        try:
            api.execute(call_name, call_data)
        except ConnectionError as e:
            reply = api.response.reply
            vals = dict()
            vals['severity_code_error'] = True
            vals['severity_code_warning'] = False
            vals['error_message'] = ebay_errors(reply.Errors)
            item.write(vals)
        else:
            reply = api.response.reply
            vals = dict()
            vals['end_time'] = reply.EndTime
            vals['item_id'] = reply.ItemID
            vals['start_time'] = reply.StartTime
            vals['need_to_be_updated'] = False
            vals['bid_count'] = 0
            vals['quantity_sold'] = 0
            vals['revise_date'] = fields.datetime.now()
            vals['state'] = 'Active'
            vals['response'] = api.response.json()
            if reply.Ack == 'Warning' and reply.has_key('Errors'):
                vals['severity_code_error'] = False
                vals['severity_code_warning'] = True
                vals['error_message'] = ebay_errors(reply.Errors)
            else:
                vals['severity_code_error'] = False
                vals['severity_code_warning'] = False
                vals['error_message'] = ''
            item.write(vals)
            self.item_post_update(cr, uid, item, context=context)
            varations = item.child_ids
            if varations:
                for varation in varations:
                    varation.write({'quantity_sold': 0, 'state': item.state})
                    
    def action_verify(self, cr, uid, ids, context=None):
        try:
            for item in self.browse(cr, uid, ids, context=context):
                ebay_ebay_obj = self.pool.get('ebay.ebay')
                user = item.ebay_user_id
                
                if self.picture_upload(cr, uid, item, context=context) == False:
                    continue
                
                call_data, auction = self.item_create(cr, uid, item, context=context)
                
                if item.item_id:
                    call_data['Item']['ItemID'] = item.item_id
                    call_name = "VerifyRelistItem" if auction else "VerifyRelistFixedPriceItem"
                else:
                    call_name = "VerifyAddItem" if auction else "VerifyAddFixedPriceItem"
                
                api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
                try:
                    api.execute(call_name, call_data)
                except ConnectionError as e:
                    reply = api.response.reply
                    vals = dict()
                    vals['severity_code_error'] = True
                    vals['severity_code_warning'] = False
                    vals['error_message'] = ebay_errors(reply.Errors)
                    item.write(vals)
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'Verify Item', e, context=context)
        
        return True
            
    def action_upload_picture(self, cr, uid, ids, context=None):
        try:
            for item in self.browse(cr, uid, ids, context=context):
                self.picture_upload(cr, uid, item, context=context)
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'UploadSiteHostedPictures', e, context=context)
        
        return True
        
    def action_upload(self, cr, uid, ids, context=None):
        try:
            for item in self.browse(cr, uid, ids, context=context):
                item.item_upload(item)
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'UploadSiteHostedPictures', e, context=context)
            
        return True
    
    def is_updated(self, cr, uid, item, context=None):
        revise_date = item.revise_date
        if item.need_to_be_updated or not revise_date:
            return True
        
        check_fields = (
            'buyer_requirement_details_id',
            'condition_description_id',
            'primary_category_id',
            'return_policy_id',
            'secondary_category_id',
            'shipping_details_id',
            'description_tmpl_id',
        )
        
        for field_name in check_fields:
            field = item[field_name]
            if field:
                perm = field.perm_read()[0]
                if perm.get('write_date') > revise_date:
                    return True
        
        return False
        
    def action_revise(self, cr, uid, ids, context=None):
        def _is_updated(item):
            revise_date = item.revise_date
            if item.need_to_be_updated or not revise_date:
                return True
            
            check_fields = (
                'buyer_requirement_details_id',
                'condition_description_id',
                'primary_category_id',
                'return_policy_id',
                'secondary_category_id',
                'shipping_details_id',
                'description_tmpl_id',
            )
            
            for field_name in check_fields:
                field = item[field_name]
                if field:
                    perm = field.perm_read()[0]
                    if perm.get('write_date') > revise_date:
                        return True
            
            return False
        
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        try:
            for item in self.browse(cr, uid, ids, context=context):
                if item.state not in ('Active',) or not _is_updated(item):
                    continue
                
                user = item.ebay_user_id
                
                if self.picture_upload(cr, uid, item, context=context) == False:
                    continue
                
                if item.variation:
                    # delete variation firstly
                    has_variation_deleted = False
                    for variation in item.child_ids:
                        if variation.variation_deleted:
                            has_variation_deleted = True
                            break
                    if has_variation_deleted:
                        call_data, auction = self.item_revise(cr, uid, item, context=context)
                        call_name = "ReviseFixedPriceItem"
                        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
                        try:
                            api.execute(call_name, call_data)
                        except ConnectionError as e:
                            reply = api.response.reply
                            vals = dict()
                            vals['severity_code_error'] = True
                            vals['severity_code_warning'] = False
                            vals['error_message'] = ebay_errors(reply.Errors)
                            item.write(vals)
                            # Break off this item revise
                            continue
                        else:
                            for variation in item.child_ids:
                                if variation.variation_deleted:
                                    variation.unlink(check=False)
                                
                    # modify specific name secondly
                    if item.variation_modify_specific_name:
                        call_data, auction = self.item_revise(cr, uid, item, context=context)
                        del call_data['Item']['Variations']
                        variation_specific_name = item.variation_specific_name
                        modify_name_nodes = list()
                        for modify_name in item.variation_modify_specific_name.replace(' ', '').splitlines():
                            modify_name = modify_name.split('|')
                            modify_name_nodes.append(dict(
                                ModifyName=dict(
                                    Name=modify_name[0],
                                    NewName=modify_name[1],
                                )
                            ))
                            variation_specific_name = variation_specific_name.replace(modify_name[0], modify_name[1])
                        call_data['Item']['Variations'] = dict(
                            ModifyNameList=modify_name_nodes if len(modify_name_nodes) > 1 else modify_name_nodes[0]
                        )
                        call_name = "ReviseFixedPriceItem"
                        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
                        try:
                            api.execute(call_name, call_data)
                        except ConnectionError as e:
                            reply = api.response.reply
                            vals = dict()
                            vals['severity_code_error'] = True
                            vals['severity_code_warning'] = False
                            vals['error_message'] = ebay_errors(reply.Errors)
                            item.write(vals)
                            # Break off this item revise
                            continue
                        else:
                            item.write(dict(
                                variation_modify_specific_name='',
                                variation_specific_name=variation_specific_name,
                            ))
                            item.refresh()
                
                call_data, auction = self.item_revise(cr, uid, item, context=context)
                if call_data == False:
                    vals = dict()
                    vals['severity_code_error'] = True
                    vals['severity_code_warning'] = False
                    vals['error_message'] = 'Can not upload pictures'
                    item.write(vals)
                    return False
                call_name = "ReviseItem" if auction else "ReviseFixedPriceItem"
                api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
                try:
                    api.execute(call_name, call_data)
                except ConnectionError as e:
                    reply = api.response.reply
                    vals = dict()
                    vals['severity_code_error'] = True
                    vals['severity_code_warning'] = False
                    vals['error_message'] = ebay_errors(reply.Errors)
                    item.write(vals)
                    # Break off this item revise
                else:
                    reply = api.response.reply
                    vals = dict()
                    vals['end_time'] = api.response.reply.EndTime
                    vals['need_to_be_updated'] = False
                    vals['revise_date'] = fields.datetime.now()
                    vals['response'] = api.response.json()
                    if reply.Ack == 'Warning' and reply.has_key('Errors'):
                        vals['severity_code_error'] = False
                        vals['severity_code_warning'] = True
                        vals['error_message'] = ebay_errors(reply.Errors)
                    else:
                        vals['severity_code_error'] = False
                        vals['severity_code_warning'] = False
                        vals['error_message'] = ''
                    item.write(vals)
                    self.item_post_update(cr, uid, item, context=context)
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'Revise Item', e, context=context)
        
        return True
    
    def action_revise_quantity(self, cr, uid, ids, context=None):
        try:
            self.revise_quantity(cr, uid, ids, context=context)
        except (ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'Revise Item Quantity', e, context=context)
        
        return True
        
    def action_synchronize(self, cr, uid, ids, context=None):
        for item in self.browse(cr, uid, ids, context=context):
            if item.state not in ('Active', 'Completed', 'Ended'):
                continue
            
            user = item.ebay_user_id
            
            call_data = dict()
            call_data['IncludeWatchCount'] = 'true'
            call_data['ItemID'] = item.item_id
            call_data['DetailLevel'] = 'ReturnAll'
            call_data['OutputSelector'] =  [
                'Item.HitCount',
                'Item.ListingDetails',
                'Item.SellingStatus',
                'Item.TimeLeft',
                'Item.Variations.Variation',
                'Item.WatchCount',
            ]
            error_msg = 'Get item: %s' % item.name
            api = self.pool.get('ebay.ebay').call(cr, uid, user, 'GetItem', call_data, error_msg, context=context)
            reply = api.response.reply
            vals = dict()
            vals['hit_count'] = reply.Item.HitCount
            listing_details = reply.Item.ListingDetails
            vals['end_time'] = listing_details.EndTime
            vals['start_time'] = listing_details.StartTime
            selling_status = reply.Item.SellingStatus
            vals['bid_count'] = selling_status.BidCount
            vals['quantity_sold'] = selling_status.QuantitySold
            vals['state'] = selling_status.ListingStatus
            vals['time_left'] = reply.Item.TimeLeft
            vals['update_date'] = fields.datetime.now()
            vals['watch_count'] = reply.Item.WatchCount
            if reply.Item.has_key('Variations'):
                for variation in reply.Item.Variations.Variation:
                    _id = variation.SKU if variation.has_key('SKU') and variation.SKU.isdigit() else ''
                    if _id:
                        record = self.browse(cr, uid, int(_id), context=context)
                        if record.exists():
                            record.write(dict(quantity_sold=variation.SellingStatus.QuantitySold))
            item.write(vals)
            self.item_post_update(cr, uid, item, context=context)
            
            def eps_picture_fetch(item):
                eps_pictures = item.eps_picture_ids
                if eps_pictures:
                    for picture in eps_pictures:
                        vals = dict()
                        if picture.dummy:
                            try:
                                vals['image'] = base64.encodestring(urllib2.urlopen(picture.full_url).read())
                            except:
                                pass
                            else:
                                vals['dummy'] = False
                                picture.write(vals)
            eps_picture_fetch(item)
            varations = item.child_ids
            if varations:
                for varation in varations:
                    eps_picture_fetch(varation)
        return True
        
    def action_end_listing(self, cr, uid, ids, context=None):
        try:
            for item in self.browse(cr, uid, ids, context=context):
                if item.state not in ('Active',):
                    continue
                try:
                    user = item.ebay_user_id
                    auction = item.listing_type == 'Chinese'
                    call_name = "EndItem" if auction else "EndFixedPriceItem"
                    call_data = dict()
                    call_data['EndingReason'] = 'NotAvailable'
                    call_data['ItemID'] = item.item_id
                    api = self.pool.get('ebay.ebay').trading(cr, uid, user, call_name, context=context)
                    api.execute(call_name, call_data)
                except ConnectionError as e:
                    reply = api.response.reply
                    vals = dict()
                    vals['severity_code_error'] = True
                    vals['severity_code_warning'] = False
                    vals['error_message'] = ebay_errors(reply.Errors)
                    item.write(vals)
                else:
                    reply = api.response.reply
                    vals = dict()
                    vals['variation_modify_specific_name'] = ''
                    vals['end_time'] = api.response.reply.EndTime
                    vals['state'] = 'Completed'
                    vals['severity_code_error'] = False
                    vals['severity_code_warning'] = False
                    vals['error_message'] = ''
                    item.write(vals)
                    varations = item.child_ids
                    if varations:
                        for varation in varations:
                            varation.write(dict(state='Completed'))
        except (ConnectionError, ConnectionResponseError, RequestException) as e:
            return self.pool.get('ebay.ebay').exception(cr, uid, 'UploadSiteHostedPictures', e, context=context)
            
        return True
        
    def action_renew_uuid(self, cr, uid, ids, context=None):
        for item in self.browse(cr, uid, ids, context=context):
            if item.state not in ('Completed','Ended'):
                continue
            item.write(dict(uuid=uuid.uuid1().hex))
        
        return True
    
    def action_create_variations(self, cr, uid, ids, context=None):
        for item in self.browse(cr, uid, ids, context=context):
            print item.variation_specifics_set
            if item.variation_specifics_set:
                variations = ['']
                for specific_values in split_str(item.variation_specifics_set, '\n'):
                    specific_values = split_str(specific_values, '|')
                    specific_values_len = len(specific_values)
                    if specific_values_len == 0:
                        continue
                    variations_len = len(variations)
                    values = []
                    for value in specific_values:
                        values += [value] * variations_len
                    variations = variations * specific_values_len
                    for i, value in enumerate(values):
                        variations[i] = variations[i] + value + '\n'
                for variation in variations:
                    domain = [('variation_specifics_set', '=', variation), ('parent_id', '=', item.id)]
                    ids = self.search(cr, uid, domain, context=context)
                    if ids:
                        print variation, 'found'
                        continue
                    else:
                        print variation, 'not found'
                        vals = dict(
                            quantity=item.quantity,
                            start_price=item.start_price,
                            name='[%s]' % ']['.join(split_str(variation, '\n')),
                            variation_specifics_set=variation,
                            parent_id=item.id,
                        )
                        self.create(cr, uid, vals, context=context)
        
        return True
        
    def variation_quantity_dict(self, cr, uid, item, child_ids=None, context=None): 
        user = item.ebay_user_id
        variations_dict = dict()
        
        specific_names = split_str(item.variation_specific_name, '|')
        
        variants = list()
        for variant in child_ids:
            index = 0
            name_value_list = list()
            for value in split_str(variant.variation_specifics_set, '\n'):
                name_value_list.append(dict(
                    Name=specific_names[index],
                    Value=value,
                ))
                index+=1
            v = dict(
                    Quantity=variant.quantity,
                    SKU=variant.id,
                    StartPrice=variant.start_price,
                    VariationSpecifics=dict(
                        NameValueList=name_value_list if len(name_value_list) > 1 else name_value_list[0],
                    )
                )
            variants.append(v)
        variations_dict['Variation'] = variants if len(variants) > 1 else variants[0]
            
        name_value_list = list()
        index = 0
        for specific_values in split_str(item.variation_specifics_set, '\n'):
            if specific_values:
                specific_values = split_str(specific_values, '|')
                name_value_list.append(dict(
                    Name=specific_names[index],
                    Value=specific_values if len(specific_values) > 1 else specific_values[0]
                ))
                index+=1
        variations_dict['VariationSpecificsSet'] = dict(
            NameValueList=name_value_list if len(name_value_list) > 1 else name_value_list[0]
        )
        
        return variations_dict
    
    def revise_item_quantity(self, cr, uid, item, child_ids=None, context=None):
        user = item.ebay_user_id
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        call_data = {
            'Item': {
                'ItemID': item.item_id,
                
            },
            #'InvocationID': item.uuid,
        }
        if item.shipping_details_id:
            call_data['Item']['ShippingDetails'] = item.shipping_details_id.dict(user, item.shipping_details_id)
        if child_ids:
            call_data['Item']['Variations'] = self.variation_quantity_dict(cr, uid, item, child_ids, context=context)
        else:
            call_data['Item']['Quantity'] = item.quantity
        call_name = "ReviseFixedPriceItem"
        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
        try:
            reply = api.execute(call_name, call_data).reply
        except ConnectionError as e:
            vals = dict()
            vals['response'] = api.response.json()
            vals['severity_code_error'] = True
            vals['severity_code_warning'] = False
            vals['error_message'] = ebay_errors(api.response.reply.Errors)
            item.write(vals)
        else:
            vals = dict()
            vals['revise_date'] = fields.datetime.now()
            vals['response'] = api.response.json()
            if reply.Ack == 'Warning' and reply.has_key('Errors'):
                vals['severity_code_error'] = False
                vals['severity_code_warning'] = True
                vals['error_message'] = ebay_errors(reply.Errors)
            else:
                vals['severity_code_error'] = False
                vals['severity_code_warning'] = False
                vals['error_message'] = ''
            item.write(vals)
    
    def revise_quantity(self, cr, uid, ids, context=None):
        def _eligible_item(item):
            if item.quantity != item.quantity_surplus and item.product_ids:
                for product in item.product_ids:
                    if product.product_id.state in ['end', 'obsolete']:
                        return False
                return True
            return False
        
        for item in self.browse(cr, uid, ids, context=context):
            if not item.variation_invalid and item.variation:
                child_ids = []
                for variation in item.child_ids:
                    if _eligible_item(variation):
                        child_ids.append(variation)
                if len(child_ids):
                    self.revise_item_quantity(cr, uid, item, child_ids, context=context)
            else:
                if _eligible_item(item):
                    self.revise_item_quantity(cr, uid, item, context=context)
    
    def action_dummy(self, cr, uid, ids, context=None):
        for item in self.browse(cr, uid, ids, context=context):
            pass
        
ebay_item()

class ebay_item_description_template(osv.osv):
    _name = "ebay.item.description.template"
    _description = "eBay item description template"
    
    _columns = {
        'name': fields.char('Name', required=True, select=True),
        'template': fields.text('Template'),
        'ebay_item_ids': fields.one2many('ebay.item', 'description_tmpl_id', 'Item'),
    }
    
    _defaults = {
    }
    
ebay_item_description_template()
