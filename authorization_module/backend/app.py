from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, stream_with_context
from flask_cors import CORS
from authorizer_service import AuthorizerService
import secrets
import requests

app = Flask(__name__, template_folder='template')
app.secret_key = secrets.token_hex(16)  # Generate a secure secret key
CORS(app)

authorizer_service = AuthorizerService()

@app.route('/')
def index():
    """Redirect to login if not authenticated, otherwise to dashboard"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET'])
def login():
    """Render login page"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    """Handle login request"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required'}), 400
    
    result = authorizer_service.login(username, password)
    
    if result['success']:
        session['user'] = result['user']
        return jsonify(result), 200
    
    return jsonify(result), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    """Handle logout request"""
    session.pop('user', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

@app.route('/dashboard')
def dashboard():
    """Render dashboard - requires authentication"""
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/api/accidents', methods=['GET'])
def get_accidents():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    status = request.args.get('status')

    # normalize status
    if status:
        status = status.upper()

    if status == 'UPLOADED':
        accidents = authorizer_service.get_uploaded_accidents()
    elif status:
        accidents = authorizer_service.get_accidents_by_status(status)
    else:
        accidents = authorizer_service.get_all_accidents()

    return jsonify({'success': True, 'data': accidents}), 200

@app.route('/api/accidents/<accident_id>', methods=['GET'])
def get_accident(accident_id):
    """Get specific accident details"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    accident = authorizer_service.get_accident_details(accident_id)
    
    if accident:
        return jsonify({'success': True, 'data': accident}), 200
    return jsonify({'success': False, 'message': 'Accident not found'}), 404

@app.route('/api/accidents/<accident_id>/approve', methods=['POST'])
def approve_accident(accident_id):
    """Approve an accident report"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['user']['username']
    result = authorizer_service.approve_accident(accident_id, username)
    
    if result['success']:
        return jsonify(result), 200
    return jsonify(result), 400

@app.route('/api/accidents/<accident_id>/reject', methods=['POST'])
def reject_accident(accident_id):
    """Reject an accident report"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    username = session['user']['username']
    result = authorizer_service.reject_accident(accident_id, username)
    
    if result['success']:
        return jsonify(result), 200
    return jsonify(result), 400

@app.route('/api/video-proxy/<path:video_path>')
def video_proxy(video_path):
    """Proxy video requests to bypass CORS"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Construct the Supabase storage URL
    supabase_url = f"https://fhqiewinlrphsaottdwe.supabase.co/storage/v1/object/public/videos/{video_path}"
    
    print(f"🎥 Proxying video request: {video_path}")
    print(f"🔗 Supabase URL: {supabase_url}")
    
    try:
        # Get range header if present (for video seeking)
        range_header = request.headers.get('Range')
        req_headers = {}
        
        if range_header:
            req_headers['Range'] = range_header
            print(f"📊 Range request: {range_header}")
        else:
            print(f"📊 Full file request (no range)")
        
        # Make request to Supabase
        req = requests.get(supabase_url, headers=req_headers, stream=True, timeout=30)
        
        print(f"✅ Supabase response status: {req.status_code}")
        print(f"📦 Content-Type from Supabase: {req.headers.get('content-type')}")
        print(f"📏 Content-Length: {req.headers.get('content-length')}")
        
        if req.status_code not in [200, 206]:
            print(f"❌ Error: Supabase returned status {req.status_code}")
            return jsonify({'error': 'Video not found'}), 404
        
        # Force correct content-type for video files
        content_type = 'video/mp4'  # Always use video/mp4 for .mp4 files
        print(f"🔄 Setting content-type to: {content_type}")
        
        # Prepare response headers with proper video streaming headers
        response_headers = {
            'Content-Type': content_type,
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-cache',  # Prevent caching issues
        }
        
        # Add content length if available
        if 'content-length' in req.headers:
            response_headers['Content-Length'] = req.headers['content-length']
        
        # Add content range if present (for partial content)
        if 'content-range' in req.headers:
            response_headers['Content-Range'] = req.headers['content-range']
        
        print(f"📤 Sending video with status {req.status_code} and headers: {response_headers}")
        
        # Create response generator
        def generate():
            try:
                for chunk in req.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception as e:
                print(f"❌ Error streaming video: {e}")
        
        # Return response
        response = Response(
            generate(),
            status=req.status_code,
            headers=response_headers,
            mimetype=content_type
        )
        
        return response
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error proxying video: {e}")
        return jsonify({'error': 'Failed to load video', 'details': str(e)}), 500

@app.route('/api/accidents/<accident_id>/video', methods=['GET'])
def get_video(accident_id):
    """Get video URL for an accident"""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    video_url = authorizer_service.get_video_url(accident_id)
    
    if video_url:
        return jsonify({'success': True, 'video_url': video_url}), 200
    return jsonify({'success': False, 'message': 'Video not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)