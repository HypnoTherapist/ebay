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
from datetime import datetime, timedelta
import time

from openerp import pooler, tools
from openerp.osv import fields, osv, orm
from openerp.tools.translate import _

import base64
import urllib2
import json

from jinja2 import Template

sys.path.insert(0, '%s/ebaysdk-python/' % os.path.dirname(__file__))

from ebay_utils import *
import ebaysdk
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError, ConnectionResponseError
from requests.exceptions import RequestException

_logger = logging.getLogger(__name__)
    
class ebay_ebay(osv.osv):
    _name = "ebay.ebay"
    _description = "eBay"
    _site_id_domainname_dict = {
        '0': 'ebay.com',
        '2': 'ebay.ca',
        '3': 'ebay.co.uk',
        '15': 'ebay.au',
        '201': 'ebay.hk',
    }
    
    def to_default_format(self, cr, uid, timestamp, context=None):
        if type(timestamp) == datetime:
            return timestamp.strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT)
        else:
            date = parser.parse(timestamp)
            return date.strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT)
    
    def to_iso8601_format(self, cr, uid, timestamp, context=None):
        if type(timestamp) == datetime:
            return timestamp.isoformat()
        else:
            date = (parser.parse(timestamp))
            return date.isoformat()
        
    def format_errors(self, cr, uid, errors, context=None):
        if type(errors) != list:
            errors = [errors]
            
        template = '''
<h2>{{ error.ShortMessage }}</h2>
<ul>
  <li><b>{{ error.LongMessage }}</b></li>
  <li>Error Classification: {{ error.ErrorClassification }}</li>
  <li>Severity Code: {{ error.SeverityCode }}</li>
  <li>Error Code: {{ error.ErrorCode }}</li>
{% if error_parameters %}
  <li>
    <ul>
    {% for error_parameter in error_parameters %}
      <li>{{ error_parameter._ParamID }}: {{ error_parameter.Value }}</li>
    {% endfor %}
    </ul>
  </li>
{% endif %}
</ul>
        '''
        e = ''
        t = Template(template)
        for error in errors:
            if error.has_key('ErrorParameters'):
                error_parameters = error.ErrorParameters
                if type(error_parameters) != list:
                    error_parameters = [error_parameters]
            else:
                error_parameters = []
            e += t.render(
            error=error,
            error_parameters=error_parameters,
        )
        return e
        
    def dump_resp(self, cr, uid, api, context=None):
        print("ebay api dump")

        if api.warnings():
            print("Warnings" + api.warnings())
    
        if api.response.content:
            print("Call Success: %s in length" % len(api.response.content))
    
        print("Response code: %s" % api.response_code())
        print("Response DOM1: %s" % api.response_dom())
        print("Response ETREE: %s" % api.response.dom())
    
        print(api.response.content)
        print(api.response.json())
    
    def _get_domainname_by_site_id(self, cr, uid, site_id, context=None):
        return self._site_id_domainname_dict.get(site_id, self._site_id_domainname_dict['0'])
    
    def get_ebay_sign_in_url(self, cr, uid, site_id, sandbox, ru_name, session_id, context=None):
        url = ''
        domainname = self._get_domainname_by_site_id(self, cr, uid, site_id)
        if sandbox:
            url = 'https://signin.sandbox.%s/ws/eBayISAPI.dll?SignIn&runame=%s&SessID=%s' % (domainname, ru_name, session_id)
        else:
            url = 'https://signin.%s/ws/eBayISAPI.dll?SignIn&runame=%s&SessID=%s' % (domainname, ru_name, session_id)
            
        return url
    
    def get_ebay_api_domain(self, cr, uid, site_id, sandbox, context=None):
        url = ''
        domainname = self._get_domainname_by_site_id(self, cr, uid, site_id)
        if sandbox:
            url = 'api.sandbox.%s' % domainname
        else:
            url = 'api.%s' % domainname
            
        return url
    
    def get_auth_user(self, cr, uid, sandbox_user_included, context=None):
        ebay_user_obj = self.pool.get('ebay.user')
        domain = [('ownership', '=', True), ('ebay_auth_token', '!=', False)]
        if not sandbox_user_included:
            domain.append(('sandbox', '=', False))
        ids = ebay_user_obj.search(cr, uid, domain, context=context)
        if not ids:
            raise orm.except_orm(_('Warning!'), _('Can not find an authorized user'))
            
        return ebay_user_obj.browse(cr, uid, ids, context=context)
    
    def get_arbitrary_auth_user(self, cr, uid, sandbox, context=None):
        ebay_user_obj = self.pool.get('ebay.user')
        ids = ebay_user_obj.search(cr, uid,
                [('sandbox', '=', sandbox), ('ownership', '=', True), ('ebay_auth_token', '!=', False)], context=context)
        if not ids:
            raise orm.except_orm(_('Warning!'), _('Can not find an authorized user'))
            
        return ebay_user_obj.browse(cr, uid, ids[0], context=context)
    
    def trading(self, cr, uid, user, call_name, parallel=None, context=None):
        api = Trading(domain=self.pool.get('ebay.ebay').get_ebay_api_domain(cr, uid, user.sale_site, user.sandbox), parallel=parallel)
            
        if user.ownership:
            api.config.set('appid', user.app_id, force=True)
            api.config.set('devid', user.dev_id, force=True)
            api.config.set('certid', user.cert, force=True)
        
        if call_name not in ('GetSessionID', 'FetchToken'):
            token = ''
            if user.ownership and user.ebay_auth_token:
                api.config.set('token', user.ebay_auth_token, force=True)
            else:
                auth_user = self.get_arbitrary_auth_user(cr, uid, user.sandbox, context)
                api.config.set('appid', auth_user.app_id, force=True)
                api.config.set('devid', auth_user.dev_id, force=True)
                api.config.set('certid', auth_user.cert, force=True)
                api.config.set('token', auth_user.ebay_auth_token, force=True)
                
        return api
    
    def call(self, cr, uid, user, call_name, call_data=dict(), error_msg='', files=None, context=None):
        try:
            api = self.trading(cr, uid, user, call_name, context=context)
            api.execute(call_name, call_data, files=files)
        except ConnectionError as e:
            raise orm.except_orm(_('Warning!'), _('%s: %s' % (error_msg, e)))
        except ConnectionResponseError as e:
            raise orm.except_orm(_('Warning!'), _('%s: %s' % (error_msg, e)))
        except RequestException as e:
            raise orm.except_orm(_('Warning!'), _('%s: %s' % (error_msg, e)))
        else:
            return api

ebay_ebay()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
