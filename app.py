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

# Prefer environment variable; fallback to hardcoded only if present
API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
if API_KEY:
    genai.configure(api_key=API_KEY)

# Lazily initialize the model to avoid import-time failures in serverless
_model = None

def get_model():
    global _model
    if _model is None:
        if not API_KEY:
            raise RuntimeError("Missing API key. Set 'GEMINI_API_KEY' or 'GOOGLE_API_KEY'.")
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
    You are a cautious first-aid triage assistant analyzing a single image and short text.
    Your top priority is to AVOID FALSE POSITIVES. Do not infer an injury unless there is
    objective, visible evidence in the image.

    Decision rule:
    - First, list objective visual evidence (e.g., bleeding, open wound, swelling, deformity,
      bruising, rash, redness, burns, bite marks, foreign body, obvious infection signs).
    - If you cannot identify clear evidence of injury, explicitly state:
      "No clear injury is visible in the image." Then provide brief general guidance only
      (e.g., monitor for symptoms) and STOP. Do not fabricate injuries.
    - If evidence exists, proceed with a cautious differential (top 1–2 likely possibilities),
      immediate first-aid steps, and when to seek medical care.

    Output format (use these headings):
    1) Visual Evidence Found
    2) Assessment (say "No clear injury visible" if none)
    3) Immediate First Aid (only if injury likely)
    4) When to Seek Medical Care
    5) Trusted India Resources (publicly accessible links only)
    6) Helpline (India)
    7) Confidence: Low / Medium / High
    8) Disclaimer

    Constraints:
    - Keep advice non-diagnostic and first-aid focused.
    - Use Indian resources and phone numbers when providing links/helplines.
    - If the image is unrelated to a human injury, state that plainly and do not assume harm.
    - Be concise and avoid alarmist language, especially when confidence is Low.

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