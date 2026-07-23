from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import requests
import re
import os
from datetime import datetime
import imaplib
import email
from email.header import decode_header
import time
import json
import logging
import base64

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'fampay-secret-key-2026')
CORS(app)

# Configuration
FAMPAY_API_URL = os.environ.get('FAMPAY_API_URL', 'https://fampaygateway.site/api/create_order.php')
FAMPAY_API_KEY = os.environ.get('FAMPAY_API_KEY', 'FAM_9D6E3230864644382B11215E46E93283144AE8A4')

# In-memory storage
user_data = {
    'gmail_email': None,
    'gmail_password': None,
    'fampay_upi': '9304619487@fam',  # 🔥 DEFAULT UPI SET
    'balance': 173.0,  # 🔥 DEFAULT BALANCE SET
    'transactions': [],
    'monitoring': False
}

class FamPayGateway:
    @staticmethod
    def create_order(amount, upi_id=None):
        """Create payment order via FamPay Gateway API"""
        try:
            params = {
                'amount': amount,
                'api_key': FAMPAY_API_KEY
            }
            if upi_id:
                params['upi_id'] = upi_id
            
            logger.info(f"📤 Creating order: ₹{amount}")
            response = requests.get(FAMPAY_API_URL, params=params, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📥 Response: {data}")
                if data.get('status') == 'success':
                    return {'success': True, 'data': data['data']}
                else:
                    return {'success': False, 'error': data.get('message', 'API Error')}
            else:
                return {'success': False, 'error': f'HTTP {response.status_code}'}
        except Exception as e:
            logger.error(f"Order creation error: {e}")
            return {'success': False, 'error': str(e)}

class GmailMonitor:
    @staticmethod
    def parse_payment_email(body, subject):
        """Parse payment details from FamPay email"""
        try:
            # Extract amount
            amount_match = re.search(r'₹([\d.]+)', body)
            if not amount_match:
                return None
            
            amount = float(amount_match.group(1))
            
            # Extract sender
            sender_match = re.search(r'from\s+([A-Z\s]+)', body)
            sender = sender_match.group(1).strip() if sender_match else "Unknown"
            
            # Extract transaction ID
            txn_match = re.search(r'Transaction ID\s*:\s*([A-Z0-9]+)', body)
            txn_id = txn_match.group(1) if txn_match else None
            
            # Extract UTR
            utr_match = re.search(r'UTR\s*:\s*(\d+)', body)
            utr = utr_match.group(1) if utr_match else None
            
            # Extract date
            date_match = re.search(r'Date\s*:\s*([\d:APM\s]+)', body)
            date_str = date_match.group(1) if date_match else None
            
            # Extract updated balance
            balance_match = re.search(r'Updated Balance\s*:\s*₹([\d.]+)', body)
            new_balance = float(balance_match.group(1)) if balance_match else None
            
            return {
                'amount': amount,
                'sender': sender,
                'transaction_id': txn_id,
                'utr': utr,
                'date': date_str,
                'new_balance': new_balance,
                'timestamp': datetime.now().isoformat(),
                'status': 'success'
            }
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return None
    
    @staticmethod
    def check_emails(email_address, app_password):
        """Check Gmail for FamPay emails"""
        try:
            app_password = app_password.replace(' ', '')
            
            # Connect to Gmail IMAP
            imap = imaplib.IMAP_SSL("imap.gmail.com")
            imap.login(email_address, app_password)
            imap.select("INBOX")
            
            # Search for FamPay emails
            status, messages = imap.search(None, '(SUBJECT "famapp" OR SUBJECT "FamX" OR TEXT "famapp" OR TEXT "FamApp" OR TEXT "received")')
            
            if status != 'OK':
                imap.close()
                imap.logout()
                return []
            
            email_ids = messages[0].split()
            payments = []
            
            # Check last 10 emails
            for e_id in email_ids[-10:]:
                status, msg_data = imap.fetch(e_id, '(RFC822)')
                if status != 'OK':
                    continue
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        # Parse subject
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or 'utf-8')
                        
                        # Parse body
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if content_type == "text/plain" and "attachment" not in content_disposition:
                                    body = part.get_payload(decode=True).decode()
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode()
                        
                        # Parse payment data
                        payment_data = GmailMonitor.parse_payment_email(body, subject)
                        if payment_data:
                            payment_data['email_id'] = e_id.decode()
                            payments.append(payment_data)
            
            imap.close()
            imap.logout()
            return payments
        except Exception as e:
            logger.error(f"Gmail check error: {e}")
            return []

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html',
                         balance=user_data['balance'],
                         transactions=user_data['transactions'],
                         upi_id=user_data.get('fampay_upi', '9304619487@fam'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """Setup page"""
    if request.method == 'POST':
        gmail_email = request.form.get('gmail_email')
        gmail_password = request.form.get('gmail_password')
        fampay_upi = request.form.get('fampay_upi')
        
        try:
            test_payments = GmailMonitor.check_emails(gmail_email, gmail_password)
            
            user_data['gmail_email'] = gmail_email
            user_data['gmail_password'] = gmail_password
            if fampay_upi:
                user_data['fampay_upi'] = fampay_upi
            user_data['monitoring'] = True
            
            # Process existing payments
            for payment in test_payments:
                if not any(t.get('transaction_id') == payment.get('transaction_id') 
                          for t in user_data['transactions']):
                    user_data['balance'] += payment['amount']
                    user_data['transactions'].append(payment)
            
            return jsonify({
                'success': True,
                'message': 'Setup successful!',
                'payments_found': len(test_payments),
                'balance': user_data['balance']
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Gmail authentication failed: {str(e)}'
            })
    
    return render_template('setup.html')

@app.route('/api/create_order', methods=['POST'])
def create_order():
    """Create payment order API"""
    try:
        data = request.json
        amount = data.get('amount')
        
        if not amount or float(amount) <= 0:
            return jsonify({'error': 'Invalid amount'}), 400
        
        result = FamPayGateway.create_order(amount, user_data.get('fampay_upi'))
        
        if result['success']:
            return jsonify({
                'status': 'success',
                'data': result['data']
            })
        else:
            return jsonify({
                'status': 'error',
                'error': result['error']
            }), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/check_payments', methods=['POST'])
def check_payments():
    """Check for new payments manually"""
    try:
        if not user_data.get('gmail_email') or not user_data.get('gmail_password'):
            return jsonify({'error': 'Gmail not configured'}), 400
        
        payments = GmailMonitor.check_emails(
            user_data['gmail_email'],
            user_data['gmail_password']
        )
        
        new_payments = []
        for payment in payments:
            # Check if already processed
            if not any(t.get('transaction_id') == payment.get('transaction_id') 
                      for t in user_data['transactions']):
                user_data['balance'] += payment['amount']
                user_data['transactions'].append(payment)
                new_payments.append(payment)
        
        return jsonify({
            'new_payments': new_payments,
            'balance': user_data['balance'],
            'total_transactions': len(user_data['transactions'])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_qr')
def get_qr():
    """Get QR code for UPI"""
    upi_id = user_data.get('fampay_upi', '9304619487@fam')
    
    # Generate QR with amount support
    amount = request.args.get('amount', '')
    if amount:
        qr_data = f"upi://pay?pa={upi_id}&pn=FamPay&am={amount}&cu=INR"
    else:
        qr_data = f"upi://pay?pa={upi_id}&pn=FamPay&cu=INR"
    
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={qr_data}"
    
    return jsonify({
        'qr_url': qr_url,
        'upi_id': upi_id,
        'qr_data': qr_data
    })

@app.route('/api/transactions')
def get_transactions():
    """Get all transactions"""
    return jsonify({
        'transactions': user_data['transactions'][-20:],
        'balance': user_data['balance'],
        'total': len(user_data['transactions'])
    })

@app.route('/api/balance')
def get_balance():
    """Get current balance"""
    return jsonify({
        'balance': user_data['balance'],
        'upi_id': user_data.get('fampay_upi', '9304619487@fam')
    })

@app.route('/api/webhook', methods=['POST'])
def webhook():
    """Webhook for external payment notifications"""
    try:
        data = request.json
        payment = {
            'amount': float(data.get('amount', 0)),
            'sender': data.get('sender', 'Webhook'),
            'transaction_id': data.get('transaction_id', f'WEB_{int(time.time())}'),
            'utr': data.get('utr', ''),
            'date': datetime.now().strftime('%H:%M %p IST, %d %B %Y'),
            'timestamp': datetime.now().isoformat(),
            'status': 'success'
        }
        
        user_data['balance'] += payment['amount']
        user_data['transactions'].append(payment)
        
        return jsonify({'status': 'success', 'payment': payment})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Route not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)