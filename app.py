import google.generativeai as genai
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import mimetypes
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Use writable temp dir on Vercel; fallback to local static/uploads during dev
_default_upload = 'static/uploads'
_vercel_upload = '/tmp/uploads'
app.config['UPLOAD_FOLDER'] = (
    _vercel_upload if os.environ.get('VERCEL') == '1' else _default_upload
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

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
    input_prompt = """This image shows a person with an injury or visible symptoms on the body.
    Please analyze the image along with the prompted message and identify the possible injury.
    Based on your analysis, suggest appropriate first aid measures that can be taken to address the injury.
    And also provides useful website links (Indian links only) which are valid and existing
    and which can give more information regarding the first aid for the injury and also
    Ensure the target website links are publicly accessible and not blocked by firewalls or login requirements.
    And also provide contact information of the helpline for the next steps. And constrain the response to India.
    The prompted message is """

    image_prompt = input_image_setup(image_path)
    prompt_parts = [input_prompt + text_input, image_prompt[0]]
    model = get_model()
    response = model.generate_content(prompt_parts)
    return getattr(response, "text", "") or "No response generated."

@app.route('/')
def index():
    return render_template('index.html')

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