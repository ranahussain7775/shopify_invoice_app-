import os
import shopify
from flask import Flask, render_template, Response, abort, request, send_file, session, redirect, url_for
from weasyprint import HTML, CSS
import qrcode
import base64
from io import BytesIO
import zipfile
import datetime
import time

# Flask app initialize kora
app = Flask(__name__)
# Session bebohar korar jonno ekta secret key proyojon
app.secret_key = os.urandom(24) 
app.config['PROPAGATE_EXCEPTIONS'] = True

# === Kendrio Helper Function (Refactored) ===
# Ei ekti function ekhn sob order details, image, ebong QR code fetch korbe
def fetch_and_prepare_order_details(order_id):
    try:
        # Shopify API rate limit thik rakhar jonno proti request e ektu biroti
        time.sleep(0.5) 
        order = shopify.Order.find(order_id)
        if not order:
            return None

        for item in order.line_items:
            try:
                time.sleep(0.5) # Proti product er jonno arektu biroti
                product = shopify.Product.find(item.product_id)
                item.image_url = product.images[0].src if product.images else "https://placehold.co/80x80/eee/ccc?text=No+Image"
            except Exception:
                item.image_url = "https://placehold.co/80x80/eee/ccc?text=Error"

        qr_data = "https://dazzleusa.store/" # Apnar store er link
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        # order object er moddhei QR code ti add kore deya hocche
        order.qr_code_image = base64.b64encode(buffered.getvalue()).decode('utf-8') 
        
        return order
    except Exception as e:
        print(f"Order details fetch korte truti {order_id}: {e}")
        return None

# === Notun: Login & Session Management ===
@app.before_request
def setup_shopify_connection():
    # Login/Logout page chara onno je kono page e gele check korbe
    if request.endpoint in ['login', 'static', 'logout']:
        return
    
    # Jodi session e credential na thake, login page e pathiye dibe
    if 'api_key' not in session:
        return redirect(url_for('login'))
    
    # Session theke credential niye Shopify connection toiri korbe
    try:
        shop_url_str = f"https://{session['api_key']}:{session['api_password']}@{session['shop_url']}/admin/api/2024-04"
        shopify.ShopifyResource.set_site(shop_url_str)
    except Exception as e:
        print(f"Shopify songjoge truti: {e}")
        session.clear() # Somossa hole session clear kore login page e pathabe
        return redirect(url_for('login'))

# === Notun: Login Page Route ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        shop_url = request.form['shop_url']
        api_key = request.form['api_key']
        api_password = request.form['api_password']

        try:
            # Connection test kora
            site = f"https://{api_key}:{api_password}@{shop_url}/admin/api/2024-04"
            shopify.ShopifyResource.set_site(site)
            shopify.Shop.current() # Test fetch
            
            # Connection safol hole, tottho session e save kora
            session['shop_url'] = shop_url
            session['api_key'] = api_key
            session['api_password'] = api_password
            print("Shopify-er sathe safolbhabe songjukto hoyeche!")
            
            return redirect(url_for('index')) # Order page e pathiye deya
        except Exception as e:
            error_msg = f"Connection failed. Error: {e}"
            print(error_msg)
            return render_template('login.html', error="Could not connect. Please check credentials.")

    return render_template('login.html') # GET request e login page dekhabe

# === Notun: Logout Route ===
@app.route('/logout')
def logout():
    session.clear() # Session theke sob data muche fela
    return redirect(url_for('login'))

# === Apnar Purono: Mul Order Page (Updated) ===
@app.route('/')
def index():
    try:
        payment_status = request.args.get('payment_status', 'any')
        fulfillment_status = request.args.get('fulfillment_status', 'any')
        
        # Order 'created_at DESC' jog kora hoyeche jate notun order upore thake
        params = {'limit': 250, 'status': 'any', 'order': 'created_at DESC'} 
        if payment_status != 'any':
            params['financial_status'] = payment_status
        if fulfillment_status != 'any':
            params['fulfillment_status'] = fulfillment_status
            
        orders = shopify.Order.find(**params)
        
        return render_template('index.html', 
                               orders=orders, 
                               payment_status=payment_status, 
                               fulfillment_status=fulfillment_status)
    except Exception as e:
        return f"Order ante somossa hoyeche: {e}"

# === Apnar Purono: Ekok Invoice Route (Updated) ===
@app.route('/invoice/<int:order_id>')
def generate_invoice(order_id):
    # Ekhn notun helper function call kora hocche
    order_data = fetch_and_prepare_order_details(order_id)
    if not order_data:
        return abort(404, "Could not find order data.")

    # PDF generate korar logic ekhn route er moddhe
    html_string = render_template('invoice_template.html', order=order_data, qr_code_image=order_data.qr_code_image)
    pdf_style = CSS(string='@page { size: A5 landscape; margin: 0.7cm; }')
    pdf_bytes = HTML(string=html_string).write_pdf(stylesheets=[pdf_style])
    filename = f"Invoice-{order_data.name.replace('#','')}.pdf"
    
    action = request.args.get('action', 'view') 
    disposition = 'attachment' if action == 'download' else 'inline'
    
    return Response(pdf_bytes, mimetype="application/pdf", headers={"Content-Disposition": f"{disposition}; filename=\"{filename}\""})

# === Apnar Purono: ZIP Download Route (Updated) ===
@app.route('/download-zip')
def download_zip():
    order_ids_str = request.args.get('order_ids')
    if not order_ids_str:
        return "No order IDs provided", 400
        
    order_ids = order_ids_str.split(',')
    memory_file = BytesIO()
    
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for order_id in order_ids:
            # Ekhaneo notun helper function call kora hocche
            order_data = fetch_and_prepare_order_details(int(order_id))
            if order_data:
                # PDF generate korar logic ekhn route er moddhe
                html_string = render_template('invoice_template.html', order=order_data, qr_code_image=order_data.qr_code_image)
                pdf_style = CSS(string='@page { size: A5 landscape; margin: 0.7cm; }')
                pdf_bytes = HTML(string=html_string).write_pdf(stylesheets=[pdf_style])
                filename = f"Invoice-{order_data.name.replace('#','')}.pdf"
                zf.writestr(filename, pdf_bytes) # ZIP file e PDF add kora
                
    memory_file.seek(0)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_filename = f"Invoices_{timestamp}.zip"
    
    return send_file(memory_file, download_name=zip_filename, as_attachment=True, mimetype='application/zip')

# === Apnar Purono: Print Preview Route (Updated) ===
@app.route('/print-preview')
def print_preview():
    order_ids_str = request.args.get('order_ids')
    if not order_ids_str:
        return "No order IDs provided", 400

    order_ids = order_ids_str.split(',')
    orders_data = []
    for order_id in order_ids:
        # Ekhaneo notun helper function call kora hocche
        order_data = fetch_and_prepare_order_details(int(order_id))
        if order_data:
            orders_data.append(order_data)
    
    # Shudhu orders_data pathano hocche
    return render_template('print_preview.html', orders=orders_data)


if __name__ == '__main__':
    app.run(debug=False, port=os.environ.get('PORT', 8080))