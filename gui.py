import streamlit as st
import os
import subprocess
import yaml
import socket
import shutil
import threading
import schedule
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

import logging
import streamlit as st

# Define a custom logging filter
class LevelFilter(logging.Filter):
    def __init__(self, level):
        self.level = level
    def filter(self, record):
        return record.levelno >= self.level

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a stream handler for capturing logs
info_handler = logging.StreamHandler()
info_handler.setLevel(logging.INFO)
info_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Create another stream handler for error logs
error_handler = logging.StreamHandler()
error_handler.setLevel(logging.WARNING)  # Capturing WARNING and above
error_handler.addFilter(LevelFilter(logging.WARNING))
error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Add handlers to the logger
logger.addHandler(info_handler)
logger.addHandler(error_handler)




# Define paths
feeds_path = Path("input/feeds.txt")
config_path = Path("config.yaml")
uglyfeeds_dir = Path("uglyfeeds")
uglyfeed_file = "uglyfeed.xml"
static_dir = Path(".streamlit") / "static" / "uglyfeeds"
version_file = Path("version.txt")
docs_dir = Path("docs")

# Ensure necessary directories and files exist
os.makedirs("input", exist_ok=True)
os.makedirs("output", exist_ok=True)
os.makedirs("rewritten", exist_ok=True)
os.makedirs(uglyfeeds_dir, exist_ok=True)
os.makedirs(static_dir, exist_ok=True)

# Global variable to hold job execution stats
job_stats_global = []

def load_config():
    """Load existing configuration if available."""
    if config_path.exists():
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    return {}

def ensure_default_config(config_data):
    """Ensure all required keys are in the config_data with default values."""
    defaults = {
        'similarity_threshold': 0.66,
        'similarity_options': {
            'min_samples': 2,
            'eps': 0.66
        },
        'api_config': {
            'selected_api': "OpenAI",
            'openai_api_url': "https://api.openai.com/v1/chat/completions",
            'openai_api_key': "",
            'openai_model': "gpt-3.5-turbo",
            'groq_api_url': "https://api.groq.com/openai/v1/chat/completions",
            'groq_api_key': "",
            'groq_model': "llama3-70b-8192",
            'ollama_api_url': "http://localhost:11434/api/chat",
            'ollama_model': "phi3"
        },
        'folders': {
            'output_folder': "output",
            'rewritten_folder': "rewritten"
        },
        'content_prefix': "In qualità di giornalista esperto, utilizza un tono professionale, preciso e dettagliato...",
        'max_items': 50,
        'max_age_days': 10,
        'scheduling_enabled': False,
        'scheduling_interval': 2,
        'scheduling_period': 'minutes'
    }

    def recursive_update(d, u):
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = recursive_update(d.get(k, {}), v)
            else:
                d.setdefault(k, v)
        return d

    return recursive_update(config_data, defaults)

def save_configuration():
    """Save configuration and feeds to file."""
    with open(config_path, "w") as f:
        yaml.dump(st.session_state.config_data, f)
    with open(feeds_path, "w") as f:
        f.write(st.session_state.feeds)
    st.success("Configuration and feeds saved.")

def get_local_ip():
    """Get the local IP address."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(('10.254.254.254', 1))
            local_ip = s.getsockname()[0]
        except OSError:
            local_ip = '127.0.0.1'
    return local_ip

def find_available_port(base_port):
    """Find an available port starting from a base port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        while True:
            try:
                s.bind(("", base_port))
                s.close()
                return base_port
            except OSError:
                base_port += 1

def run_script(script_name):
    """Execute a script and capture its output and errors."""
    process = subprocess.run(["python", script_name], capture_output=True, text=True)
    output = process.stdout.strip() if process.stdout else "No output"
    errors = process.stderr.strip() if process.stderr else "No errors"
    return output, errors

def run_scripts_sequentially():
    """Run main.py, llm_processor.py, and json2rss.py sequentially and log their outputs."""
    global job_stats_global
    scripts = ["main.py", "llm_processor.py", "json2rss.py"]
    item_count_before = get_xml_item_count()

    # Prepare containers for output and error logs
    info_log_content = []
    error_log_content = []

    for script in scripts:
        with st.spinner(f"Executing {script}..."):
            output, errors = run_script(script)

            # Collect logs for Streamlit display
            info_log_content.append(f"Output of {script}:\n{output}")
            if errors.strip() and errors != "No errors":
                error_log_content.append(f"Errors or logs of {script}:\n{errors}")

            # Log output and errors
            logger.info(f"Output of {script}:\n{output}")
            if errors.strip() and errors != "No errors":
                logger.error(f"Errors or logs of {script}:\n{errors}")

            # Display output and errors in Streamlit text areas
            st.text_area(f"Output of {script}", output, height=200)
            #  if errors.strip() and errors != "No errors":
            #    st.text_area(f"Errors or logs of {script}", errors, height=200)

    new_items = get_new_item_count(item_count_before)
    job_stats_global.append({
        'script': ', '.join(scripts),
        'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'status': 'Success',
        'new_items': new_items
    })

    # Display consolidated logs
    if info_log_content:
        st.text_area("Consolidated Output Log", "\n".join(info_log_content), height=200)
    if error_log_content:
        st.text_area("Consolidated Error Log", "\n".join(error_log_content), height=200)




class XMLHTTPRequestHandler(SimpleHTTPRequestHandler):
    """Custom HTTP handler to serve XML with correct content type and cache headers."""
    def do_GET(self):
        if self.path.endswith(".xml"):
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0")
            self.end_headers()
            with open(static_dir / self.path.lstrip('/'), 'rb') as file:
                self.wfile.write(file.read())
        else:
            super().do_GET()

def start_custom_server(port):
    """Start the HTTP server to serve XML."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, XMLHTTPRequestHandler)
    httpd.serve_forever()

def stop_server():
    """Stop the HTTP server."""
    if st.session_state.server_thread and st.session_state.server_thread.is_alive():
        st.session_state.server_thread = None
        st.warning("Server stopped. Please restart the application to stop the server completely.")

def toggle_server(start):
    """Toggle the HTTP server on or off."""
    if start:
        if st.session_state.server_thread is None or not st.session_state.server_thread.is_alive():
            st.session_state.custom_server_port = 8001  # Fixed port
            st.session_state.server_thread = threading.Thread(target=start_custom_server, args=(st.session_state.custom_server_port,), daemon=True)
            st.session_state.server_thread.start()
            st.success(f"Server started on port {st.session_state.custom_server_port}")
        else:
            st.warning("Server is already running.")
    else:
        stop_server()

def copy_xml_to_static():
    """Ensure XML is copied to Streamlit static directory."""
    if uglyfeeds_dir.exists() and (uglyfeeds_dir / uglyfeed_file).exists():
        destination_path = static_dir / uglyfeed_file
        shutil.copy(uglyfeeds_dir / uglyfeed_file, destination_path)
        return destination_path
    return None

def list_markdown_files(docs_dir):
    """List all Markdown files in the docs directory."""
    return [file for file in docs_dir.glob("*.md")]

def get_xml_stats():
    """Get quick stats from the XML file."""
    if not (uglyfeeds_dir / uglyfeed_file).exists():
        return None, None, None
    tree = ET.parse(uglyfeeds_dir / uglyfeed_file)
    root = tree.getroot()
    items = root.findall(".//item")
    item_count = len(items)
    last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return item_count, last_updated, uglyfeeds_dir / uglyfeed_file

def get_xml_item_count():
    """Get the current count of items in the XML."""
    if not (uglyfeeds_dir / uglyfeed_file).exists():
        return 0
    tree = ET.parse(uglyfeeds_dir / uglyfeed_file)
    root = tree.getroot()
    items = root.findall(".//item")
    return len(items)

def get_new_item_count(old_count):
    """Calculate the new items count based on the old count."""
    new_count = get_xml_item_count()
    if old_count is None or new_count is None:
        return 0
    return new_count - old_count

def schedule_jobs(interval, period):
    """Schedule jobs to run periodically."""
    def job():
        run_scripts_sequentially()
        job_stats_global.append({
            'script': 'Scheduled Job',
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'Success'
        })

    if period == 'minutes':
        schedule.every(interval).minutes.do(job)
    elif period == 'hours':
        schedule.every(interval).hours.do(job)
    elif period == 'days':
        schedule.every(interval).days.do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)

# Initialize session state
if 'config_data' not in st.session_state:
    st.session_state.config_data = ensure_default_config(load_config())
if 'server_thread' not in st.session_state:
    st.session_state.server_thread = None

# Load RSS feeds
if 'feeds' not in st.session_state:
    if feeds_path.exists():
        with open(feeds_path, "r") as f:
            st.session_state.feeds = f.read()
    else:
        st.session_state.feeds = ""

# Start scheduling if enabled in the config
if st.session_state.config_data.get('scheduling_enabled', False):
    scheduling_thread = threading.Thread(target=schedule_jobs, args=(st.session_state.config_data['scheduling_interval'], st.session_state.config_data['scheduling_period']), daemon=True)
    scheduling_thread.start()

# Sidebar navigation
st.sidebar.title("Navigation")
menu_options = [
    "Introduction",
    "Configuration",
    "Run Scripts",
    "View and Serve XML",
    "Debug"
]
selected_option = st.sidebar.selectbox("Select an option", menu_options)

# Introduction Page
if selected_option == "Introduction":
    st.title("UglyFeed")
    st.image("docs/UglyFeed.png", width=300, use_column_width='auto')
    st.write("""
        This application provides a graphical user interface to manage and process RSS feeds using the UglyFeed project.
        Use the sidebar to navigate through different functionalities of the application:

        - **Configuration**: Set up and save your RSS feeds and processing options.
        - **Run Scripts**: Execute various processing scripts like `main.py`, `llm_processor.py`, and `json2rss.py`.
        - **View and Serve XML**: View the content of the XML feed and serve it via a custom HTTP server.
        - **Debug**: View detailed debug information for troubleshooting.

        Ensure your local environment is correctly set up and necessary directories and files are in place.
        For any issues, [open an issue on GitHub](https://github.com/fabriziosalmi/UglyFeed/issues/new/choose). Enjoy!
    """)

# Configuration Section
elif selected_option == "Configuration":
    st.header("Configuration")

    st.divider()

    st.subheader("RSS Feeds")
    st.session_state.feeds = st.text_area("Enter one RSS feed URL per line:", st.session_state.feeds)

    st.divider()

    st.subheader("Similarity Options")
    st.session_state.config_data['similarity_threshold'] = st.slider("Similarity Threshold", 0.0, 1.0, st.session_state.config_data['similarity_threshold'])
    st.session_state.config_data['similarity_options']['min_samples'] = st.number_input("Minimum Samples", min_value=1, value=st.session_state.config_data['similarity_options']['min_samples'])
    st.session_state.config_data['similarity_options']['eps'] = st.number_input("Epsilon (eps)", min_value=0.0, value=st.session_state.config_data['similarity_options']['eps'], step=0.01)

    st.divider()

    st.subheader("API and LLM Options")
    api_options = ["OpenAI", "Groq", "Ollama"]
    selected_api = st.selectbox("Select API", api_options, index=api_options.index(st.session_state.config_data['api_config']['selected_api']))
    st.session_state.config_data['api_config']['selected_api'] = selected_api

    if selected_api == "OpenAI":
        st.session_state.config_data['api_config']['openai_api_url'] = st.text_input("OpenAI API URL", st.session_state.config_data['api_config']['openai_api_url'])
        st.session_state.config_data['api_config']['openai_api_key'] = st.text_input("OpenAI API Key", st.session_state.config_data['api_config']['openai_api_key'], type="password")
        st.session_state.config_data['api_config']['openai_model'] = st.text_input("OpenAI Model", st.session_state.config_data['api_config']['openai_model'])
    elif selected_api == "Groq":
        st.session_state.config_data['api_config']['groq_api_url'] = st.text_input("Groq API URL", st.session_state.config_data['api_config']['groq_api_url'])
        st.session_state.config_data['api_config']['groq_api_key'] = st.text_input("Groq API Key", st.session_state.config_data['api_config']['groq_api_key'], type="password")
        st.session_state.config_data['api_config']['groq_model'] = st.text_input("Groq Model", st.session_state.config_data['api_config']['groq_model'])
    else:
        st.session_state.config_data['api_config']['ollama_api_url'] = st.text_input("Ollama API URL", st.session_state.config_data['api_config']['ollama_api_url'])
        st.session_state.config_data['api_config']['ollama_model'] = st.text_input("Ollama Model", st.session_state.config_data['api_config']['ollama_model'])

    st.divider()

    st.subheader("Content Prefix")
    st.session_state.config_data['content_prefix'] = st.text_area("Content Prefix", st.session_state.config_data['content_prefix'])

    st.divider()

    st.subheader("RSS Retention Options")
    st.session_state.config_data['max_items'] = st.number_input("Maximum Items", min_value=1, value=st.session_state.config_data['max_items'])
    st.session_state.config_data['max_age_days'] = st.number_input("Maximum Age (days)", min_value=1, value=st.session_state.config_data['max_age_days'])

    st.divider()

    st.subheader("Scheduling Options")
    scheduling_enabled = st.session_state.config_data.get('scheduling_enabled', False)
    st.session_state.config_data['scheduling_enabled'] = st.checkbox("Enable Scheduled Execution", value=scheduling_enabled)

    interval_options = {
        "2 minutes": (2, 'minutes'),
        "10 minutes": (10, 'minutes'),
        "30 minutes": (30, 'minutes'),
        "1 hour": (1, 'hours'),
        "4 hours": (4, 'hours'),
        "12 hours": (12, 'hours'),
        "24 hours": (24, 'hours')
    }
    default_interval = next((k for k, v in interval_options.items() if v == (st.session_state.config_data.get('scheduling_interval', 2), st.session_state.config_data.get('scheduling_period', 'minutes'))), "2 minutes")
    selected_interval = st.selectbox("Select Scheduling Interval", list(interval_options.keys()), index=list(interval_options.keys()).index(default_interval))

    interval, period = interval_options[selected_interval]
    st.session_state.config_data['scheduling_interval'] = interval
    st.session_state.config_data['scheduling_period'] = period

    if st.button("Save Configuration and Feeds"):
        save_configuration()

# Run Scripts Section
elif selected_option == "Run Scripts":
    st.header("Run Scripts")

    if st.button("Run main.py, llm_processor.py, and json2rss.py sequentially"):
        run_scripts_sequentially()

# View and Serve XML Section
elif selected_option == "View and Serve XML":
    st.header("View and Serve XML")

    xml_file_path = copy_xml_to_static()
    if not xml_file_path:
        st.warning(f"The file '{uglyfeed_file}' does not exist in the directory '{uglyfeeds_dir}'.")
    else:
        with open(xml_file_path, "r") as f:
            xml_content = f.read()
        st.text_area("XML Content", xml_content, height=300)

        with open(xml_file_path, "rb") as f:
            st.download_button(
                label="Download XML File",
                data=f,
                file_name=uglyfeed_file,
                mime="application/xml"
            )

        st.subheader("Control HTTP Server for XML Serving")
        if st.button("Start HTTP Server"):
            toggle_server(True)
        if st.button("Stop HTTP Server"):
            toggle_server(False)

        if st.session_state.server_thread and st.session_state.server_thread.is_alive():
            local_ip = get_local_ip()
            serve_url = f"http://{local_ip}:{st.session_state.custom_server_port}/{uglyfeed_file}"
            st.markdown(f"**Serving `{uglyfeed_file}` at:**\n\n[{serve_url}]({serve_url})")
        else:
            st.info("Server is not running.")

# Debug Section
elif selected_option == "Debug":
    st.header("Debug")

    st.subheader("Job Execution Logs")
    if job_stats_global:
        for stat in job_stats_global:
            st.markdown(f"**Script:** `{stat['script']}`")
            st.markdown(f"**Time:** `{stat['time']}`")
            st.markdown(f"**Status:** `{stat['status']}`")
            st.markdown(f"**New Items:** `{stat.get('new_items', 0)}`")
            st.divider()
    else:
        st.info("No job executions have been recorded yet.")

    st.subheader("XML File Stats")
    item_count, last_updated, xml_path = get_xml_stats()
    if item_count is not None:
        st.write(f"**Item Count:** `{item_count}`")
        st.write(f"**Last Updated:** `{last_updated}`")
        st.write(f"**File Path:** `{xml_path}`")
    else:
        st.info("No XML file found or file is empty.")

    st.subheader("Current Configuration")
    st.text_area("Config.yaml Content", yaml.dump(st.session_state.config_data), height=300)

    st.subheader("Loaded Feeds")
    st.text_area("Feeds Content", st.session_state.feeds, height=200)
