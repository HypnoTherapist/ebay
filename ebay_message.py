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
from datetime import datetime, timedelta

from jinja2 import Template

from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare
from openerp import pooler, tools
from dateutil.relativedelta import relativedelta
from openerp.osv import fields, osv, orm
from openerp import netsvc
from openerp.tools.translate import _
import pytz
from openerp import SUPERUSER_ID

from requests import exceptions
from ebay_utils import *
import ebaysdk
from ebaysdk.utils import getNodeText
from ebaysdk.exception import ConnectionError, ConnectionResponseError

class ebay_message_synchronize(osv.TransientModel):
    _name = 'ebay.message.synchronize'
    _description = 'eBay message synchronize'
    
    _columns = {
        'number_of_days': fields.selection([
            ('1', '1'),
            ('2', '2'),
            ('3', '3'),
            ('5', '5'),
            ('7', '7'),
            ('15', '15'),
            ('30', '30'),
            ], 'Number Of Days'),
        'message_status': fields.selection([
            ('Unanswered', 'Unanswered'),
            ('Answered', 'Answered'),
            ('CustomCode', 'CustomCode')], 'Message Status'),
        'after_service_message': fields.boolean('After Service Message'),
        'ignoe_order_before': fields.datetime('Ignore Orders Before'),
        'sandbox_user_included': fields.boolean ('Sandbox User Included'),
        'exception': fields.text('Exception', readonly=True),
        'state': fields.selection([
            ('option', 'option'),
            ('exception', 'exception')]),
    }
    
    _defaults = {
        'number_of_days': '2',
        'after_service_message': False,
        'ignoe_order_before': (datetime.now() - timedelta(45)).strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT),
        'sandbox_user_included': False,
        'exception': '',
        'state': 'option'
    }
    
    def view_init(self, cr, uid, fields_list, context=None):
        return False
    
    def action_sync(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        this = self.browse(cr, uid, ids)[0]
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_message_obj =  self.pool.get('ebay.message')
        ebay_message_media_obj =  self.pool.get('ebay.message.media')
        ebay_sale_order_obj = self.pool.get('ebay.sale.order')
            
        if this.after_service_message:
            now_time = datetime.now()
            for user in ebay_ebay_obj.get_auth_user(cr, uid, this.sandbox_user_included, context=context):
                entries_per_page = 100
                page_number = 1
                total_number_of_entries = entries_per_page
                while total_number_of_entries == entries_per_page:
                    call_data=dict()
                    call_data['FeedbackType'] = 'FeedbackReceivedAsSeller'
                    call_data['Pagination'] = {
                        'EntriesPerPage': entries_per_page,
                        'PageNumber': page_number,
                    }
                    call_data['DetailLevel'] = 'ReturnAll'
                    error_msg = 'Get the feedback for the specified user %s' % user.name
                    reply = ebay_ebay_obj.call(cr, uid, user, 'GetFeedback', call_data, error_msg, context=context).response.reply
                    if not reply.FeedbackDetailArray:
                        raise osv.except_osv(_('No Message Found.'),_('No FeedbackDetailArray returned.'))
                        
                    total_number_of_entries = int(reply.PaginationResult.TotalNumberOfEntries)
                    feedback_details = reply.FeedbackDetailArray.FeedbackDetail
                    if type(feedback_details) != list:
                        feedback_details = [feedback_details]
                    for feedback_detail in feedback_details:
                        if (now_time-feedback_detail.CommentTime).days > int(this.number_of_days):
                            total_number_of_entries = 0
                        domain = [('order_id','=',feedback_detail.OrderLineItemID)]
                        ids = ebay_sale_order_obj.search(cr, uid, domain, context=context)
                        if ids:
                            ebay_sale_order = ebay_sale_order_obj.browse(cr, uid, ids, context=context)[0]
                            if ebay_sale_order.state != 'done':
                                ebay_sale_order.write(dict(state='done'))
                                ebay_sale_order.refresh()
                        pass
                    pass
            # search matched order
            domain = [('state', '=', 'sent'), ('shipped_time', '>', this.ignoe_order_before)]
            ids = ebay_sale_order_obj.search(cr, uid, domain, context=context)
            if ids:
                for ebay_sale_order in ebay_sale_order_obj.browse(cr, uid, ids, context=context):
                    shipping_time = ebay_sale_order_obj.shipping_time(cr, uid, ebay_sale_order, context=context)
                    duration = ebay_sale_order.after_service_duration
                    if shipping_time > 7 and (duration == '0' or not duration):
                        res = ebay_message_obj.send_after_service_message(cr, uid, ebay_sale_order, '7', context=context)
                    elif shipping_time > 15 and duration == '7':
                        res = ebay_message_obj.send_after_service_message(cr, uid, ebay_sale_order, '15', context=context)
                    elif shipping_time > 25 and duration == '15':
                        res = ebay_message_obj.send_after_service_message(cr, uid, ebay_sale_order, '25', context=context)
                    else:
                        res = True
                    if res != True:
                        this.exception = res
                        break
        else:
            end_creation_time = datetime.now()
            start_creation_time = end_creation_time - timedelta(int(this.number_of_days))
            
            for user in ebay_ebay_obj.get_auth_user(cr, uid, this.sandbox_user_included, context=context):
                entries_per_page = 100
                page_number = 1
                has_more_items = True
                while has_more_items:
                    call_data=dict()
                    call_data['EndCreationTime'] = end_creation_time
                    call_data['MailMessageType'] = 'All'
                    if this.message_status:
                        call_data['MessageStatus'] = this.message_status
                    call_data['StartCreationTime'] = start_creation_time
                    call_data['Pagination'] = {
                        'EntriesPerPage': entries_per_page,
                        'PageNumber': page_number,
                    }
                    error_msg = 'Get the messages for the specified user %s' % user.name
                    reply = ebay_ebay_obj.call(cr, uid, user, 'GetMemberMessages', call_data, error_msg, context=context).response.reply
                    has_more_items = reply.HasMoreItems == 'true'
                    if reply.has_key('MemberMessage'):
                        messages = reply.MemberMessage.MemberMessageExchange
                        if type(messages) != list:
                            messages = [messages]
                        for message in messages:
                            # find existing message
                            domain = [('message_id', '=', message.Question.MessageID), ('ebay_user_id', '=', user.id)]
                            ids = ebay_message_obj.search(cr, uid, domain, context=context)
                            if ids:
                                ebay_message = ebay_message_obj.browse(cr, uid, ids[0], context=context)
                                last_modified_date = message.LastModifiedDate
                                if ebay_message.last_modified_date != ebay_strftime(last_modified_date):
                                    # last modified
                                    vals = dict(
                                        last_modified_date=message.LastModifiedDate,
                                        state=message.MessageStatus,
                                    )
                                    ebay_message.write(vals)
                                    pass
                            else:
                                # create new message
                                vals = dict(
                                    name=message.Question.Subject,
                                    body=message.Question.Body,
                                    message_type=message.Question.MessageType,
                                    question_type=message.Question.QuestionType,
                                    recipient_or_sender_id=message.Question.SenderID,
                                    sender_email=message.Question.SenderEmail,
                                    message_id=message.Question.MessageID,
                                    last_modified_date=message.LastModifiedDate,
                                    state=message.MessageStatus,
                                    ebay_user_id=user.id,
                                    type='in',
                                )
                                if message.has_key('Item'):
                                    vals['item_id'] = message.Item.ItemID
                                    vals['title'] = message.Item.Title
                                    vals['end_time'] = message.Item.ListingDetails.EndTime
                                    vals['start_time'] = message.Item.ListingDetails.StartTime
                                    vals['current_price'] = message.Item.SellingStatus.CurrentPrice.value
                                ebay_message_id = ebay_message_obj.create(cr, uid, vals, context=context)
                                
                                message_medias = []
                                if message.has_key('MessageMedia'):
                                    message_medias.extend(message.MessageMedia if type(message.MessageMedia) == list else [message.MessageMedia])
                                if message.Question.has_key('MessageMedia'):
                                    message_medias.extend(message.Question.MessageMedia if type(message.Question.MessageMedia) == list else [message.Question.MessageMedia])
                                if message_medias:
                                    for media in message_medias:
                                        vals = dict(
                                            name=media.MediaName,
                                            image=base64.encodestring(urllib2.urlopen(media.MediaURL).read()),
                                            full_url=media.MediaURL,
                                            message_id=ebay_message_id,
                                        )
                                        ebay_message_media_obj.create(cr, uid, vals, context=context)
    
                    page_number = page_number + 1
                    
        if this.exception:
            self.write(cr, uid, [this.id], {
                                  'exception': this.exception,
                                  'state': 'exception'}, context=context)
            return  {
                'name': "Send / Recieve",
                'type': 'ir.actions.act_window',
                'res_model': 'ebay.message.synchronize',
                'view_mode': 'form',
                'view_type': 'form',
                'res_id': this.id,
                'views': [(False, 'form')],
                'target': 'new',
            }
        if this.after_service_message:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Sent',
                'view_mode': 'tree,form',
                'view_type': 'form',
                'res_model': 'ebay.message',
                'domain': "[('type','=','out')]",
                'context': "{'default_type':'out'}]",
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Inbox',
                'view_mode': 'tree,form',
                'view_type': 'form',
                'res_model': 'ebay.message',
                'domain': "[('type','=','in')]",
                'context': "{'default_type':'in'}]",
            }

class ebay_message_media(osv.osv):
    _name = "ebay.message.media"
    _description = "eBay member message"
    
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
        'name': fields.char('Name', size=100, required=True),
        # image: all image fields are base64 encoded and PIL-supported
        'image': fields.binary("Image",
            help="This field holds the image used as avatar for this contact, limited to 1024x1024px"),
        'image_medium': fields.function(_get_image, fnct_inv=_set_image,
            string="Medium-sized image", type="binary", multi="_get_image",
            store={
                'ebay.message.media': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Medium-sized image of this contact. It is automatically "\
                 "resized as a 128x128px image, with aspect ratio preserved. "\
                 "Use this field in form views or some kanban views."),
        'image_small': fields.function(_get_image, fnct_inv=_set_image,
            string="Small-sized image", type="binary", multi="_get_image",
            store={
                'ebay.message.media': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Small-sized image of this contact. It is automatically "\
                 "resized as a 64x64px image, with aspect ratio preserved. "\
                 "Use this field anywhere a small image is required."),
        'has_image': fields.function(_has_image, type="boolean"),
        'full_url': fields.char('URL', readonly=True),
        'picture_format': fields.char('PictureFormat', readonly=True),
        'use_by_date': fields.datetime('UseByDate', readonly=True),
        'message_id': fields.many2one('ebay.message', 'Message', readonly=True, ondelete='cascade'),
    }
    
ebay_message_media()
    
class ebay_message(osv.osv):
    _name = "ebay.message"
    _description = "eBay member message"
    
    def _get_message_chat(self, cr, uid, ids, field_name, arg, context):
        if context is None:
            context = {}
        ebay_message_obj =  self.pool.get('ebay.message')
        template = '''
{{ sender_id }}    {{ last_modified_date }}
----------------------------------------------------------
{{ body }}


        '''
        chat_template = Template(template)
        res = {}
        for record in self.browse(cr, uid, ids, context=context):
            res[record.id] = ''
            ebay_user_id = record.recipient_or_sender_id
            item_id = record.item_id
            last_modified_date = record.last_modified_date
            if ebay_user_id and item_id:
                #domain = [('recipient_or_sender_id', '=', ebay_user_id), ('item_id', '=', item_id), ('last_modified_date', '<', last_modified_date)]
                domain = [('recipient_or_sender_id', '=', ebay_user_id), ('item_id', '=', item_id)]
                ids = ebay_message_obj.search(cr, uid, domain, context=context)
                if ids:
                    chat = ''
                    for msg in ebay_message_obj.browse(cr, uid, ids, context=context):
                        chat += chat_template.render(
                            sender_id=msg.recipient_or_sender_id if msg.type == 'in' else msg.ebay_user_id.name,
                            last_modified_date=msg.last_modified_date,
                            body=msg.body,
                        )
                    res[record.id] = chat
        return res

    _columns = {
        'name': fields.char('Subject', required=True),
        'body': fields.text('Body', required=True),
        'message_type': fields.selection([
            ('All', 'All'),
            ('AskSellerQuestion', 'AskSellerQuestion'),
            ('ClassifiedsBestOffer', 'ClassifiedsBestOffer'),
            ('ClassifiedsContactSeller', 'ClassifiedsContactSeller'),
            ('ContactEbayMember', 'ContactEbayMember'),
            ('ContacteBayMemberViaAnonymousEmail', 'ContacteBayMemberViaAnonymousEmail'),
            ('ContacteBayMemberViaCommunityLink', 'ContacteBayMemberViaCommunityLink'),
            ('ContactMyBidder', 'ContactMyBidder'),
            ('ContactTransactionPartner', 'ContactTransactionPartner'),
            ('CustomCode', 'CustomCode'),
            ('ResponseToASQQuestion', 'ResponseToASQQuestion'),
            ('ResponseToContacteBayMember', 'ResponseToContacteBayMember'),
            ], 'MessageType', readonly=True),
        'question_type': fields.selection([
            ('CustomCode', 'CustomCode'),
            ('CustomizedSubject', 'CustomizedSubject'),
            ('General', 'General'),
            ('MultipleItemShipping', 'MultipleItemShipping'),
            ('None', 'None'),
            ('Payment', 'Payment'),
            ('Shipping', 'Shipping'),
        ], 'QuestionType'),
        'recipient_or_sender_id': fields.char('Recipient / Sender', readonly=True),
        'sender_email': fields.char('Sender Email', size=240),
        
        'item_id': fields.char('Item ID', size=38, readonly=True),
        'title': fields.char('Title', readonly=True),
        'end_time': fields.datetime('End Time', readonly=True),
        'start_time': fields.datetime('Start Time', readonly=True),
        'current_price': fields.float('CurrentPrice', readonly=True),
        
        'media_ids': fields.one2many('ebay.message.media', 'message_id', 'Media'),
        'message_id': fields.char('MessageID', help='ID that uniquely identifies a message for a given user.'),
        'parent_message_id': fields.char('Parent MessageID', help='ID number of the question to which this message is responding.'),
        
        'last_modified_date': fields.datetime('LastModifiedDate', readonly=True),
        'state': fields.selection([
            ('Draft', 'Draft'),
            ('Sent', 'Sent'),
            ('CustomCode', 'CustomCode'),
            ('Unanswered', 'Unanswered'),
            ('Answered', 'Answered'),], 'MessageStatus', readonly=True),
        'chat': fields.function(_get_message_chat, type='text', method=True, string='Chat', readonly=True),
        'type': fields.selection([
            ('in', 'in'),
            ('out', 'out'),
        ], 'Type', required=True, readonly=True, select=True),
        'automated_email': fields.boolean ('Automated Email'),
        'partner_id': fields.many2one('res.partner', 'Customer'),
        'ebay_user_id': fields.many2one('ebay.user', 'eBay User', readonly=True),
        'order_id': fields.many2one('ebay.sale.order', 'Order Reference', ondelete='cascade'),
    }
    
    _defaults = {
        'question_type': 'General',
        'state': 'Draft',
        'type': 'out',
    }
    
    _order = 'last_modified_date desc'
    
    def action_reply(self, cr, uid, ids, context=None):
        if len(ids) == 0:
            return False
        id = ids[0]
        msg = self.browse(cr, uid, id, context=context)
        ctx = dict(context)
        if msg.question_type != 'None':
            default_name = 'RE: %s about %s' % (msg.question_type, msg.title if msg.title else msg.name)
        else:
            default_name = 'RE: %s' % msg.name
        ctx.update({
            'default_model': 'ebay.message',
            'default_name': default_name,
            'default_recipient_or_sender_id': msg.recipient_or_sender_id,
            'default_item_id': msg.item_id,
            'default_title': msg.title,
            'default_end_time': msg.end_time,
            'default_start_time': msg.start_time,
            'default_current_price': msg.current_price,
            'default_question_type': msg.question_type,
            'default_parent_message_id': msg.message_id,
            'default_last_modified_date': fields.datetime.now(),
            'default_ebay_user_id': msg.ebay_user_id.id,
            'default_type': 'out',
            })
        if msg.partner_id:
            ctx['default_partner_id'] = msg.partner_id.id
        if msg.partner_id:
            ctx['default_order_id'] = msg.order_id.id
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'ebay.message',
            'target': 'new',
            'context': ctx,
        }
    
    def action_send(self, cr, uid, ids, context=None):
        if len(ids) == 0:
            return False
        id = ids[0]
        msg = self.browse(cr, uid, id, context=context)
        
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        user = msg.ebay_user_id
        
        message_media = []
        if msg.media_ids:
            for media in msg.media_ids:
                if not media.full_url:
                    image = io.BytesIO(base64.b64decode(media.image))
                    call_data = dict()
                    call_data['PictureSystemVersion'] = 2
                    call_name = 'UploadSiteHostedPictures'
                    api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
                    try:
                        api.execute(call_name, call_data, files=dict(image=image))
                    except ConnectionError as e:
                        raise orm.except_orm(_('Warning!'), e)
                    except ConnectionResponseError as e:
                        raise orm.except_orm(_('Warning!'), e)
                    except exceptions.RequestException as e:
                        raise orm.except_orm(_('Warning!'), e)
                    else:
                        reply = api.response.reply
                        site_hosted_picture_details = reply.SiteHostedPictureDetails
                        vals = dict()
                        vals['full_url'] = site_hosted_picture_details.FullURL
                        vals['picture_format'] = site_hosted_picture_details.PictureFormat
                        vals['use_by_date'] = site_hosted_picture_details.UseByDate
                        media.write(vals)
                        media.refresh()
                        
                message_media.append(dict(
                    MediaName=media.name,
                    MediaURL=media.full_url,
                ))
        
        item_id = msg.item_id
        
        if msg.parent_message_id:
            call_data=dict(
                MemberMessage=dict(
                    Body='<![CDATA[%s]]>' % msg.body,
                    ParentMessageID=msg.parent_message_id,
                    QuestionType=msg.question_type,
                    RecipientID=msg.recipient_or_sender_id,
                    Subject='<![CDATA[%s]]>' % msg.name[:99],
                )
            )
            if item_id:
                call_data['ItemID'] = item_id
            if message_media:
                call_data['MemberMessage']['MessageMedia'] = message_media if len(message_media) > 1 else message_media[0]
            call_name = 'AddMemberMessageRTQ'
        else:
            call_data=dict(
                ItemID=item_id,
                MemberMessage=dict(
                    Body='<![CDATA[%s]]>' % msg.body,
                    QuestionType=msg.question_type,
                    RecipientID=msg.recipient_or_sender_id,
                    Subject='<![CDATA[%s]]>' % msg.name[:99],
                )
            )
            if message_media:
                call_data['MemberMessage']['MessageMedia'] = message_media if len(message_media) > 1 else message_media[0]
            call_name = 'AddMemberMessageAAQToPartner'
        
        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
        try:
            api.execute(call_name, call_data)
        except ConnectionError as e:
            raise orm.except_orm(_('Warning!'), e)
        except ConnectionResponseError as e:
            raise orm.except_orm(_('Warning!'), e)
        except exceptions.RequestException as e:
            raise orm.except_orm(_('Warning!'), e)
        else:
            return msg.write(dict(
                last_modified_date=fields.datetime.now(),
                state='Sent',
            ))
        
    def send_after_service_message(self, cr, uid, ebay_sale_order, duration, context=None):
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        user = ebay_sale_order.ebay_user_id
        print 'send after server message', (ebay_sale_order.name, duration)
        if duration == '7':
            after_service_template = user.after_service_7_template
        elif duration == '15':
            after_service_template = user.after_service_15_template
        elif duration == '25':
            after_service_template = user.after_service_25_template
        else:
            after_service_template = False
        if not after_service_template:
            return 'After service template is empty!'
        
        now_time = datetime.now()
        shipped_time = datetime.strptime(ebay_sale_order.shipped_time, tools.DEFAULT_SERVER_DATETIME_FORMAT)
        delta = (now_time - shipped_time).days
        chat_template = Template(after_service_template)
        body = chat_template.render(
            shipped_time=ebay_sale_order.shipped_time,
            elapse=delta,
        )
        
        item_id = ebay_sale_order.transactions[0].item_id
        subject = 'Shipping about %s' % ebay_sale_order.transactions[0].name
        question_type = 'Shipping'
        
        call_data=dict(
            ItemID=item_id,
            MemberMessage=dict(
                Body='<![CDATA[%s]]>' % body,
                QuestionType=question_type,
                RecipientID=ebay_sale_order.buyer_user_id,
                Subject='<![CDATA[%s]]>' % subject[:99],
            )
        )
        call_name = 'AddMemberMessageAAQToPartner'
        
        api = ebay_ebay_obj.trading(cr, uid, user, call_name, context=context)
        try:
            api.execute(call_name, call_data)
        except ConnectionError as e:
            res = str(e)
        except ConnectionResponseError as e:
            res = str(e)
        except exceptions.RequestException as e:
            res = str(e)
        else:
            #reply = api.response.reply
            #reply.Ack == 'Success'
            ebay_sale_order.write(dict(after_service_duration=duration))
            vals=dict(
                name=subject,
                body=body,
                question_type=question_type,
                recipient_or_sender_id=ebay_sale_order.buyer_user_id,
                item_id=ebay_sale_order.transactions[0].item_id,
                title=ebay_sale_order.transactions[0].name,
                last_modified_date=fields.datetime.now(),
                state='Sent',
                type='out',
                automated_email=True,
                partner_id=ebay_sale_order.partner_id.id,
                ebay_user_id=user.id,
                order_id=ebay_sale_order.id,
            )
            self.create(cr, uid, vals, context=context)
            res = True
        return res
    
ebay_message()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: