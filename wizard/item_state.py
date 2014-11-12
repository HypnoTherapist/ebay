# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2012-Today OpenERP SA (<http://www.openerp.com>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>
#
##############################################################################

import os
import sys
import base64
import urllib2
import xlwt
import csv, codecs, cStringIO, gzip
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

import openerp
from openerp import tools
from openerp.osv import osv
from openerp.osv import fields
from openerp.tools.translate import _

import ebaysdk
from openerp.addons.ebay.ebay_utils import *
from ebaysdk.exception import ConnectionError, ConnectionResponseError
from ssl import SSLError
from requests.exceptions import RequestException

class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")

class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self

class UnicodeWriter:
    """
    A CSV writer which will write rows to CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        # Redirect output to a queue
        self.queue = cStringIO.StringIO()
        self.writer = csv.writer(self.queue, dialect=dialect, **kwds)
        self.stream = f
        self.encoder = codecs.getincrementalencoder(encoding)()

    def writerow(self, row):
        self.writer.writerow([s.encode("utf-8") for s in row])
        # Fetch UTF-8 output from the queue ...
        data = self.queue.getvalue()
        data = data.decode("utf-8")
        # ... and reencode it into the target encoding
        data = self.encoder.encode(data)
        # write to the target stream
        self.stream.write(data)
        # empty queue
        self.queue.truncate(0)

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)

class ebay_item_sync_user(osv.TransientModel):
    _name = 'ebay.item.sync.user'
    _description = 'eBay item sync user'
    
    _columns = {
        'ebay_user_id': fields.many2one('ebay.user', 'eBay User', required=True, domain=[('ownership','=',True)]),
        'autocreate': fields.boolean('Create New Item'),
        'revise_quantity': fields.boolean('Revise Quantity'),
        'count': fields.integer('New/Updated Lists', readonly=True),
        'state': fields.selection([
            ('option', 'option'),   # select ebay user option
            ('complete', 'complete')])
    }
    
    _defaults = {
        'autocreate': False,
        'revise_quantity': False,
        'state': 'option',
    }
    
    def create_inventory(self, cr, uid, this, user, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_item_obj = self.pool.get('ebay.item')
        ebay_category_obj = self.pool.get('ebay.category')
        ebay_eps_picture_obj = self.pool.get('ebay.eps.picture')
        
        count = 0
        
        img_path = openerp.modules.get_module_resource('ebay', 'static/src/img', 'icon.png')
        img_file = open(img_path, 'rb')
        img_def = base64.encodestring(img_file.read())
        
        output_selector = [
            'HasMoreItems',
            'ItemArray.Item.BuyItNowPrice',
            'ItemArray.Item.ConditionID',
            'ItemArray.Item.Currency',
            'ItemArray.Item.Description',
            'ItemArray.Item.ItemID',
            'ItemArray.Item.ListingDetails',
            'ItemArray.Item.ListingDuration',
            'ItemArray.Item.ListingType',
            'ItemArray.Item.PictureDetails',
            'ItemArray.Item.PrimaryCategory',
            'ItemArray.Item.Quantity',
            'ItemArray.Item.SellingStatus',
            'ItemArray.Item.StartPrice',
            'ItemArray.Item.Site',
            'ItemArray.Item.SKU',
            'ItemArray.Item.TimeLeft',
            'ItemArray.Item.Title',
            'ItemArray.Item.Variations',
            'ItemsPerPage',
            'PageNumber',
            'ReturnedItemCountActual',
        ]
        
        now = datetime.now()
        end_time_from = now.isoformat()
        end_time_to = (now + timedelta(32)).isoformat()
        entries_per_page = 160
        page_number = 1
        has_more_items = True
        while has_more_items:
            call_data=dict()
            call_data['EndTimeFrom'] = end_time_from
            call_data['EndTimeTo'] = end_time_to
            call_data['IncludeVariations'] = 'true'
            call_data['IncludeWatchCount'] = 'true'
            call_data['Pagination'] = {
                'EntriesPerPage': entries_per_page,
                'PageNumber': page_number,
            }
            call_data['DetailLevel'] = 'ReturnAll'
            call_data['OutputSelector'] = output_selector
            call_name = 'GetSellerList'
            api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
            reply = api.execute(call_name, call_data).reply
            has_more_items = reply.HasMoreItems == 'true'
            items = reply.ItemArray.Item
            for item in ebay_repeatable_list(reply.ItemArray.Item):
                sku = item.SKU if item.has_key('SKU') else ''
                listing_details = item.ListingDetails
                selling_status = item.SellingStatus
                
                # search exist item id
                if ebay_item_obj.search(cr, uid, [('item_id', '=', item.ItemID)], context=context):
                    continue
                
                # search exist item sku
                if sku and sku.isdigit() and ebay_item_obj.exists(cr, uid, int(sku), context=context):
                    continue
                
                vals = dict()
                vals['buy_it_now_price'] = item.BuyItNowPrice.value
                vals['condition_id'] = item.ConditionID if item.has_key('ConditionID') else None
                vals['currency'] = item.Currency
                description = item.Description
                start_token = '<!-- DESCRIPTION START -->'
                end_token = '<!-- DESCRIPTION END -->'
                start = description.find(start_token)
                end = description.find(end_token)
                if start != -1 and end != -1:
                    description = description[start+len(start_token):end]
                vals['description'] = description
                vals['listing_duration'] = item.ListingDuration
                vals['listing_type'] = item.ListingType
                
                category_id = item.PrimaryCategory.CategoryID
                category_name = item.PrimaryCategory.CategoryName
                primary_category_id = ebay_category_obj.search_category(
                    cr, uid, category_id, category_name, user.sandbox, context=context)
                vals['primary_category_id'] = primary_category_id
                
                vals['quantity'] = item.Quantity
                vals['start_price'] = item.StartPrice.value
                vals['name'] = item.Title
                
                # item status
                vals['bid_count'] = selling_status.BidCount
                vals['end_time'] = listing_details.EndTime
                vals['hit_count'] = item.HitCount if item.has_key('HitCount') else 0
                vals['item_id'] = item.ItemID
                vals['quantity_sold'] = selling_status.QuantitySold
                vals['quantity_surplus'] = int(item.Quantity) - int(selling_status.QuantitySold)
                vals['start_time'] = listing_details.StartTime
                listing_status = selling_status.ListingStatus
                vals['state'] = listing_status
                vals['time_left'] = item.TimeLeft
                vals['update_date'] = fields.datetime.now()
                vals['watch_count'] = item.WatchCount if item.has_key('WatchCount') else 0
                
                vals['ebay_user_id'] = user.id
                
                def get_eps_pictures(picture_urls):
                    index = 1
                    _eps_pictures = list()
                    if type(picture_urls) != list:
                        picture_urls = [picture_urls]
                    for url in picture_urls:
                        vals = dict(
                            name='%03d' % index,
                            full_url=url,
                            use_by_date=datetime.now() + timedelta(90),
                        )
                        index += 1
                        _eps_pictures.append(vals)
                    return _eps_pictures
                
                eps_pictures = list()
                if item.has_key('PictureDetails') and item.PictureDetails and item.PictureDetails.has_key('PictureURL'):
                    eps_pictures = get_eps_pictures(item.PictureDetails.PictureURL)
                
                def item_create(vals, eps_pictures=None):
                    id = ebay_item_obj.create(cr, uid, vals, context=context)
                    if eps_pictures:
                        for picture in eps_pictures:
                            picture['ebay_item_id'] = id
                            url = picture['full_url']
                            picture['image'] = img_def
                            picture['dummy'] = True
                            ebay_eps_picture_obj.create(cr, uid, picture, context=context)
                    return id
                
                id = item_create(vals, eps_pictures)
                
                if item.has_key('Variations'):
                    call_data = dict()
                    call_data['ItemID'] = item.ItemID
                    call_data['DetailLevel'] = 'ReturnAll'
                    call_data['OutputSelector'] =  [
                        'Item.Variations',
                    ]
                    error_msg = 'Get item: %s' % item.Title
                    reply = ebay_ebay_obj.call(cr, uid, user, 'GetItem', call_data, error_msg, context=context).response.reply
                    vals = dict(
                        variation_invalid=False,
                        variation=True,
                    )
                    variations = reply.Item.Variations
                    variation_eps_pictures = dict()
                    if variations.has_key('Pictures'):
                        pictures = variations.Pictures
                        if pictures.has_key('VariationSpecificPictureSet'):
                            picture_set = pictures.VariationSpecificPictureSet
                            if type(picture_set) != list:
                                picture_set = [picture_set]
                            for picture in picture_set:
                                variation_eps_pictures[picture.VariationSpecificValue] = get_eps_pictures(picture.PictureURL)
                            
                    def get_specifices_set(name_value_list):
                        variation_specific_name = list()
                        variation_specifics_set = ''
                        if type(name_value_list) != list:
                            name_value_list = [name_value_list]
                        for name_value in name_value_list:
                            variation_specific_name.append(name_value.Name)
                            values = name_value.Value
                            if type(values) != list:
                                values = [values]
                            if variation_specifics_set:
                                variation_specifics_set = variation_specifics_set + '\n'
                            variation_specifics_set = variation_specifics_set + '|'.join(values)
                        return '|'.join(variation_specific_name), variation_specifics_set
                    
                    vals['variation_specific_name'], vals['variation_specifics_set'] = get_specifices_set(variations.VariationSpecificsSet.NameValueList)
                    # update item variation
                    ebay_item_obj.write(cr, uid, id, vals, context=context)
                    
                    for v in ebay_repeatable_list(variations.Variation):
                        variation_specific_name, variation_specifics=get_specifices_set(v.VariationSpecifics.NameValueList)
                        specific_values = ebay_str_split(variation_specifics, '\n')
                        vals = dict(
                            quantity=v.Quantity,
                            start_price=v.StartPrice.value,
                            name="[%s]" % ']['.join(specific_values),
                            variation_specifics_set=variation_specifics,
                            parent_id = id,
                            quantity_sold=v.SellingStatus.QuantitySold,
                            quantity_surplus=int(v.Quantity) - int(v.SellingStatus.QuantitySold),
                            state=listing_status,
                        )
                        
                        # create item child variation
                        if variation_eps_pictures.has_key(specific_values[0]):
                            item_create(vals, variation_eps_pictures[specific_values[0]])
                        else:
                            item_create(vals)
                
                count += 1
            page_number = page_number + 1
        return count
        
    def _update_variation(self, cr, uid, variation, context=None):
        ebay_item_obj = self.pool.get('ebay.item')
        id = variation.SKU if variation.has_key('SKU') and variation.SKU.isdigit() else ''
        if id:
            def get_specifices_set(name_value_list):
                variation_specifics_set = ''
                if type(name_value_list) != list:
                    name_value_list = [name_value_list]
                for name_value in name_value_list:
                    values = name_value.Value
                    if type(values) != list:
                        values = [values]
                    if variation_specifics_set:
                        variation_specifics_set += '\n'
                    variation_specifics_set += '|'.join(values)
                return variation_specifics_set
            variation_specifics = get_specifices_set(variation.VariationSpecifics.NameValueList)
            specific_values = ebay_str_split(variation_specifics, '\n')
            ebay_item_obj.write(cr, uid, int(id), dict(
                name="[%s]" % ']['.join(specific_values),
                quantity_sold=variation.SellingStatus.QuantitySold,
                quantity_surplus=int(variation.Quantity) - int(variation.SellingStatus.QuantitySold)
            ),context=context)
    
    def update_inventory(self, cr, uid, this, user, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_item_obj = self.pool.get('ebay.item')
        
        count = 0
        skus = []
        
        output_selector = [
            'HasMoreItems',
            'ItemArray.Item.ItemID',
            'ItemArray.Item.ListingDetails',
            'ItemArray.Item.Quantity',
            'ItemArray.Item.SellingStatus',
            'ItemArray.Item.SKU',
            'ItemArray.Item.TimeLeft',
            'ItemArray.Item.Variations',
        ]
        now = datetime.now()
        end_time_from = (now - timedelta(32)).isoformat()
        end_time_to = (now + timedelta(32)).isoformat()
        entries_per_page = 200
        page_number = 1
        has_more_items = True
        while has_more_items:
            call_data=dict()
            call_data['EndTimeFrom'] = end_time_from
            call_data['EndTimeTo'] = end_time_to
            call_data['IncludeVariations'] = 'true'
            call_data['IncludeWatchCount'] = 'true'
            call_data['Pagination'] = {
                'EntriesPerPage': entries_per_page,
                'PageNumber': page_number,
            }
            call_data['Sort'] = 1
            call_data['DetailLevel'] = 'ReturnAll'
            call_data['OutputSelector'] = output_selector
            call_name = 'GetSellerList'
            api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
            reply = api.execute(call_name, call_data).reply
            has_more_items = reply.HasMoreItems == 'true'
            page_number = page_number + 1
            if not reply.ItemArray:
                raise osv.except_osv(_('No Item found!'), _('No ItemArray returned.'))
            for item in ebay_repeatable_list(reply.ItemArray.Item):
                sku = item.SKU if item.has_key('SKU') else ''
                if not sku or not sku.isdigit():
                    continue
                if sku in skus:
                    continue
                skus.append(sku)
                # is updated
                if ebay_item_obj.exists(cr, uid, int(sku), context=context):
                    listing_details = item.ListingDetails
                    selling_status = item.SellingStatus
                    vals = dict()
                    # item status
                    vals['bid_count'] = selling_status.BidCount
                    vals['end_time'] = listing_details.EndTime
                    vals['hit_count'] = item.HitCount if item.has_key('HitCount') else 0
                    vals['item_id'] = item.ItemID
                    vals['quantity_sold'] = selling_status.QuantitySold
                    vals['quantity_surplus'] = int(item.Quantity) - int(selling_status.QuantitySold)
                    vals['start_time'] = listing_details.StartTime
                    vals['state'] = selling_status.ListingStatus
                    vals['time_left'] = item.TimeLeft
                    vals['update_date'] = fields.datetime.now()
                    vals['watch_count'] = item.WatchCount if item.has_key('WatchCount') else 0
                    ebay_item_obj.write(cr, uid, int(sku), vals, context=context)
                    ebay_item = ebay_item_obj.browse(cr, uid, int(sku), context=context)
                    if item.has_key('Variations'):
                        for v in ebay_repeatable_list(item.Variations.Variation):
                            self._update_variation(cr, uid, v, context=context)
                    count += 1
                    
        if this.revise_quantity:
            domain = [('ebay_user_id', '=', user.id), ('state', '=', 'Active'), ('listing_type', '=', 'FixedPriceItem'), ('parent_id', '=', False)]
            ids = ebay_item_obj.search(cr, uid, domain, context=context)
            try:
                ebay_item_obj.revise_quantity(cr, uid, ids, context=context)
            except (ConnectionResponseError, RequestException) as e:
                return self.pool.get('ebay.ebay').exception(cr, uid, 'Revise Item Quantity', e, context=context)
        
        return count
    
    def action_sync(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
            
        this = self.browse(cr, uid, ids)[0]
        user = this.ebay_user_id
        if this.autocreate:
            count = self.create_inventory(cr, uid, this, user, context=context)
        else:
            count = self.update_inventory(cr, uid, this, user, context=context)
        
        vals = dict(
            count=count,
            state='complete',
        )
        self.write(cr, uid, ids, vals, context=context)
        
        return {
            'name': "Sync User Items",
            'type': 'ir.actions.act_window',
            'res_model': 'ebay.item.sync.user',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': this.id,
            'views': [(False, 'form')],
            'target': 'new',
        }
    
    def action_close(self, cr, uid, ids, context=None):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Inventory',
            'view_mode': 'tree,form',
            'view_type': 'form',
            'res_model': 'ebay.item',
            'domain': "[('parent_id','=',False)]",
        }

ebay_item_sync_user()

class ebay_item_rss(osv.TransientModel):
    _name = 'ebay.item.rss'
    _description = 'eBay item rss'
    
    _columns = {
        'ebay_user_id': fields.many2one('ebay.user', 'eBay User', required=True, domain=[('ownership','=',True)]),
        'name': fields.char('Filename', readonly=True),
        'data': fields.binary('File', readonly=True),
        'state': fields.selection([
            ('option', 'option'),
            ('download', 'download'),
        ], 'State'),
    }
    
    _defaults = {
        'state': 'option',
    }
    
    def action_export(self, cr, uid, ids, context=None):
        def rss(element=None):
            if element is not None:
                return ET.tostring(element, 'utf-8')
            return ET.Element('rss', version='2.0')
        
        def rss_channel(rss):
            rss_channel = ET.SubElement(rss, 'channel')
            title = ET.SubElement(rss_channel, 'title')
            title.text = 'title'
            link = ET.SubElement(rss_channel, 'link')
            link.text = 'link'
            description = ET.SubElement(rss_channel, 'description')
            description.text = 'description'
            return rss_channel
        
        def rss_channel_item(channel, item):
            channel_item = ET.SubElement(channel, 'item')
            title = ET.SubElement(channel_item, 'title')
            title.text = item.name
            link = ET.SubElement(channel_item, 'link')
            if item.ebay_user_id.sandbox:
                link.text = "http://cgi.sandbox.ebay.com/ws/eBayISAPI.dll?ViewItem&item=%s" % item.item_id
            else:
                link.text = "http://cgi.ebay.com/ws/eBayISAPI.dll?ViewItem&item=%s" % item.item_id
            description = ET.SubElement(channel_item, 'description')
            description.text = 'description'
            item_id = ET.SubElement(channel_item, 'itemID')
            item_id.text = item.item_id
            currency = ET.SubElement(channel_item, 'currency')
            currency.text = item.currency
            price = ET.SubElement(channel_item, 'price')
            price.text = str(item.start_price)
            return channel_item
        
        if context is None:
            context = {}
        ebay_item_obj = self.pool.get('ebay.item')
        this = self.browse(cr, uid, ids)[0]
        user = this.ebay_user_id
        domain = [('ebay_user_id', '=', user.id)]
        
        fp = cStringIO.StringIO()
        csv = UnicodeWriter(fp)
        csv.writerow(['sku', 'rss'])
        
        for id in ebay_item_obj.search(cr, uid, domain, context=context):
            item = ebay_item_obj.browse(cr, uid, id, context=context)
            id_occupy = [item.id]
            item_rss = rss()
            channel = rss_channel(item_rss)
            ebay_items = []
            for category in item.ebay_item_category_id:
                ebay_items.extend(category.ebay_item_ids)
            for itm in ebay_items:
                if itm.id not in id_occupy and itm.state == 'Active' \
                    and itm.listing_type == 'FixedPriceItem' \
                    and itm.ebay_user_id.id == user.id:
                    id_occupy.append(itm.id)
                    rss_channel_item(channel, itm)
                    # 4 x 3 table
                    if len(id_occupy) == 12 + 1:
                        break
            if len(id_occupy) > 1:
                csv.writerow([str(item.id), rss(item_rss)])
                
        gz_data = cStringIO.StringIO()
        gz = gzip.GzipFile(filename='dandelion-rss', mode='wb', fileobj=gz_data)
        gz.write(fp.getvalue())
        gz.close()
        
        out = base64.encodestring(gz_data.getvalue())
        gz_data.close()
        fp.close()
        
        this.name = "dandelion-rss-%s.gz" % (datetime.now().strftime('%Y%m%d-%H%M%S'))
        self.write(cr, uid, this.id, {'state': 'download',
                                  'data': out,
                                  'name': this.name}, context=context)
        
        return {
            'name': "Export Inventory RSS",
            'type': 'ir.actions.act_window',
            'res_model': 'ebay.item.rss',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': this.id,
            'views': [(False, 'form')],
            'target': 'new',
        }
    
ebay_item_rss()

class ebay_item_report(osv.TransientModel):
    _name = 'ebay.item.report'
    _description = 'eBay item report'
    
    _columns = {
        'listing_type': fields.selection([
            ('Chinese', 'Auction'),
            ('FixedPriceItem', 'Fixed Price'),
        ], 'Format'),
        'listing_status': fields.selection([
            ('Draft', 'Draft'),
            ('Active', 'Active'),
            ('Completed', 'Completed'),
            ('Ended', 'Ended'),
        ], 'Status'),
        'name': fields.char('Filename', readonly=True),
        'data': fields.binary('File', readonly=True),
        'state': fields.selection([
            ('option', 'option'),
            ('download', 'download'),
        ], 'State'),
    }
    
    _defaults = {
        'state': 'option',
    }
    
    def action_report(self, cr, uid, ids, context=None):
        def write_row(worksheet, row, content):
            for i, cell in enumerate(content):
                if row % 2:
                    worksheet.write(row, i, cell, xlwt.easyxf('pattern: pattern solid, fore_color light_green;'))
                else:
                    worksheet.write(row, i, cell)
        
        def item_product(item):
            if not item.product_ids:
                return ''
            
            products = ''
            for product in item.product_ids:
                if products:
                    products += '\n'
                products += '%s (x %d' % (product.product_id.name, product.uos_coeff)
                
            return products
        
        headers = [
            ('Title', (1 + 80) * 256),
            ('Status', (1 + 16) * 256),
            ('Format', (1 + 16) * 256),
            ('Duration', (1 + 8) * 256),
            ('Start Price', (1 + 16) * 256),
            ('Buy It Now Price', (1 + 16) * 256),
            ('Quantity', (1 + 16) * 256),
            ('Quantity Surplus', (1 + 16) * 256),
            ('Quantity Sold', (1 + 16) * 256),
            ('Product', (1 + 60) * 256),
        ]
        workbook = xlwt.Workbook(encoding='utf-8')
        worksheet = workbook.add_sheet('Inventory Report')
        for i, name in enumerate(headers):
            worksheet.write(0, i, name[0])
            worksheet.col(i).width = name[1]
        if context is None:
            context = {}
        ebay_item_obj = self.pool.get('ebay.item')
        this = self.browse(cr, uid, ids)[0]
        listing_type = this.listing_type
        listing_status = this.listing_status
        domain = [('parent_id', '=', False)]
        if listing_type:
            domain.append(('listing_type', '=', listing_type))
        if listing_status:
            domain.append(('state', '=', listing_status))
        
        row = 1
        for id in ebay_item_obj.search(cr, uid, domain, context=context):
            item = ebay_item_obj.browse(cr, uid, id, context=context)
            name = item.name
            if not item.variation_invalid and item.variation and item.child_ids:
                for child in item.child_ids:
                    title = '%s %s' % (item.name, child.name)
                    write_row(worksheet, row, [
                            title,
                            item.state,
                            item.listing_type,
                            item.listing_duration,
                            child.start_price,
                            None,
                            child.quantity,
                            child.quantity_surplus,
                            child.quantity_sold,
                            item_product(child),
                        ])
                    row += 1
            else:
                title = item.name
                write_row(worksheet, row, [
                        title,
                        item.state,
                        item.listing_type,
                        item.listing_duration,
                        item.start_price,
                        item.buy_it_now_price if item.buy_it_now_price and item.listing_type == 'Chinese' else None,
                        item.quantity,
                        item.quantity_surplus,
                        item.quantity_sold,
                        item_product(item),
                    ])
                row += 1
            
        fp = cStringIO.StringIO()
        workbook.save(fp)
        out = base64.encodestring(fp.getvalue())
        fp.close()
        this.name = "inventory-report-%s.xls" % (datetime.now().strftime('%Y%m%d-%H%M%S'))
        self.write(cr, uid, this.id, {'state': 'download',
                                  'data': out,
                                  'name': this.name}, context=context)
        
        return {
            'name': "Inventory Report",
            'type': 'ir.actions.act_window',
            'res_model': 'ebay.item.report',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': this.id,
            'views': [(False, 'form')],
            'target': 'new',
        }
    
ebay_item_report()

class ebay_item_sync(osv.TransientModel):
    _name = 'ebay.item.sync'
    _description = 'eBay item sync'
    
    _columns = {
        'count': fields.integer('Item record count', readonly=True),
    }
    
    def _get_count(self, cr, uid, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        return len(record_ids)
    
    _defaults = {
        'count': _get_count,
    }
    
    def get_seller_list(self, cr, uid, user, sku, context=None):
        pass
    
    def action_sync(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        
        self.pool.get('ebay.item').action_synchronize(cr, uid, record_ids, context=context)
        return {'type': 'ir.actions.act_window_close'}

ebay_item_sync()

class ebay_item_revise(osv.TransientModel):
    _name = 'ebay.item.revise'
    _description = 'eBay item revise'
    
    _columns = {
        'count': fields.integer('Item record count', readonly=True),
    }
    
    def _get_count(self, cr, uid, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        return len(record_ids)
    
    _defaults = {
        'count': _get_count,
    }
    
    def action_revise(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        res = self.pool.get('ebay.item').action_revise(cr, uid, record_ids, context=context)
        if res != True:
            return res
        else:
            return {'type': 'ir.actions.act_window_close'}

ebay_item_revise()

class ebay_item_end(osv.TransientModel):
    _name = 'ebay.item.end'
    _description = 'eBay item end'
    
    _columns = {
        'count': fields.integer('Item record count', readonly=True),
    }
    
    def _get_count(self, cr, uid, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        return len(record_ids)
    
    _defaults = {
        'count': _get_count,
    }
    
    def action_end(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        res = self.pool.get('ebay.item').action_end_listing(cr, uid, record_ids, context=context)
        if res != True:
            return res
        else:
            return {'type': 'ir.actions.act_window_close'}

ebay_item_end()

class ebay_item_upload(osv.TransientModel):
    _name = 'ebay.item.upload'
    _description = 'eBay item upload'
    
    _columns = {
        'count': fields.integer('Item record count', readonly=True),
    }
    
    def _get_count(self, cr, uid, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        return len(record_ids)
    
    _defaults = {
        'count': _get_count,
    }
    
    def action_upload(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        record_ids = context and context.get('active_ids', False)
        res = self.pool.get('ebay.item').action_upload(cr, uid, record_ids, context=context)
        if res != True:
            return res
        else:
            return {'type': 'ir.actions.act_window_close'}

ebay_item_upload()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
