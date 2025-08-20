import google.generativeai as genai
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from jinja2 import TemplateNotFound
import os
import mimetypes
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates', static_folder='static')
# Use writable temp dir on Vercel; fallback to local static/uploads during dev
_default_upload = 'static/uploads'
_vercel_upload = '/tmp/uploads'
app.config['UPLOAD_FOLDER'] = (
    _vercel_upload if os.environ.get('VERCEL') == '1' else _default_upload
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Avoid creating directories at import time in serverless

# Set up the model configuration
generation_config = {
    "temperature": 0,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 4096,
}

safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    }
]

# Inline API key option: paste your API key between the quotes below
# Example: INLINE_API_KEY = "AIza...your_key_here..."
INLINE_API_KEY = "AIzaSyAcuO7WiA8bPmjpmCwZgCtNwDJzyY7d6tU"

# Prefer environment variables; fallback to the inline key if provided
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or INLINE_API_KEY
if API_KEY:
    genai.configure(api_key=API_KEY)

# Lazily initialize the model to avoid import-time failures in serverless
_model = None

def get_model():
    global _model
    if _model is None:
        if not API_KEY:
            raise RuntimeError("Missing API key. Set 'GEMINI_API_KEY' or 'GOOGLE_API_KEY', or paste it into INLINE_API_KEY in app.py.")
        _model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config,
            safety_settings=safety_settings,
        )
    return _model

def input_image_setup(file_path):
    if not (img := Path(file_path)).exists():
        raise FileNotFoundError(f"Could not find image: {img}")

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type or not mime_type.startswith("image/"):
        raise ValueError("Unsupported file type. Please upload an image (jpg, jpeg, png, webp).")

    image_parts = [
        {
            "mime_type": mime_type,
            "data": Path(file_path).read_bytes()
        }
    ]
    return image_parts

def generate_gemini_response(text_input, image_path):
    input_prompt = """
    You are an AI-powered first aid assistant that analyzes injury photos with EXTREME ACCURACY.
    
    CRITICAL RULES - NEVER VIOLATE:
    1. ACCURATE DETECTION ONLY: Identify injuries ONLY when there is 100% clear, objective, visible evidence in the image
    2. NO FALSE INJURIES: If you cannot see clear evidence of injury, say "No injury visible" - DO NOT GUESS or assume
    3. CORRECT INJURY IDENTIFICATION: When injury IS visible, identify it precisely based on what you actually see
    4. NO FABRICATION: Never invent symptoms, conditions, or injuries that are not visible
    5. CONFIDENCE-BASED: If image is unclear, set confidence to "Low" and be very conservative

    What to look for (ONLY if clearly visible):
    - Bleeding, open wounds, cuts, lacerations
    - Swelling, bruising, redness, inflammation
    - Burns, blisters, rashes
    - Deformity, dislocation, obvious fractures
    - Bite marks, foreign objects
    - Signs of infection (pus, extreme redness, heat)

    Output format (use EXACTLY these headings):
    Visual Evidence: [Describe ONLY what is visible - if nothing, say "No clear injury visible"]
    Assessment: [State injury if present OR "No injury detected" if none visible]
    Immediate First Aid: [Steps only if injury found, else write "N/A"]
    When to Seek Medical Care: [Clear guidance based on what's visible]
    Trusted India Resources: [2-3 generic healthcare links]
    Helpline (India): Emergency number 108
    Confidence: [Low/Medium/High - Low if unclear, High only if very clear]
    Disclaimer: This is first-aid guidance only, not medical diagnosis.

    REMEMBER: Better to say "No injury visible" than to guess wrong. Accuracy over speculation.

    User note (optional context):
    """

    image_prompt = input_image_setup(image_path)
    prompt_parts = [input_prompt + (text_input or ""), image_prompt[0]]
    model = get_model()
    response = model.generate_content(prompt_parts)
    return getattr(response, "text", "") or "No response generated."

@app.route('/')
def index():
    try:
        return render_template('index.html')
    except TemplateNotFound:
        return jsonify({
            'status': 'ok',
            'note': 'Template not found in deployment bundle. Ensure templates/** is included.'
        }), 200

@app.route('/health')
def health():
    return 'ok', 200

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    
    file = request.files['image']
    text_input = request.form.get('description', '')
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file:
        # Ensure upload folder exists at request time
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            response = generate_gemini_response(text_input, filepath)
            if app.config['UPLOAD_FOLDER'].startswith('/tmp'):
                image_url = f'/uploads/{filename}'
            else:
                image_url = f'/static/uploads/{filename}'
            return jsonify({'response': response, 'image_path': image_url})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)