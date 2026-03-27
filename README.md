# Verilog Component Verification Agent

An intelligent agent powered by **LangGraph** and **Google Gemini** that automatically verifies Verilog hardware designs by analyzing component datasheets (PDF or text) and source code, iteratively identifying and fixing issues, and generating comprehensive verification reports.

## Features

📄 **Datasheet Analysis**: Analyzes component datasheets (PDF, TXT, MD) to extract specifications

🔄 **Iterative Self-Correction**: Automatically identifies issues and applies fixes across multiple iterations

🤖 **AI-Powered**: Uses Google's Gemini 2.5 Flash model for intelligent code analysis and generation

📊 **Comprehensive Reports**: Generates detailed verification reports with findings and recommendations

🏗️ **LangGraph Workflow**: Built on LangGraph for robust, stateful agent orchestration

## Architecture

The agent uses a **LangGraph state machine** with the following workflow:

```
┌─────────────────┐
│ Analyze Design  │ ← Entry Point
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Identify Issues │ ◄─────┐
└────────┬────────┘       │
         │                │
    ┌────┴────┐           │
    ▼         ▼           │
  Fix    No Issues        │
Issues      Found         │
    │         │           │
    ▼         │           │
┌─────────────┴┐          │
│ Verify Fixes │          │
└────────┬─────┘          │
         │                │
    ┌────┴────┐           │
    ▼         ▼           │
Continue   Success        │
Iteration  or Max ────────┘
           Reached
    │         │
    └─────────┼──────┐
              ▼      ▼
        ┌──────────────┐
        │Generate Report│
        └──────────────┘
              │
              ▼
            [END]
```

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd Self-Rectification-Agentic-AI
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your Google API key:

```
GOOGLE_API_KEY=your_actual_api_key_here
MAX_ITERATIONS=5
```

**Get your Google API key**: https://makersuite.google.com/app/apikey

## Usage

### 🎨 Web UI (Streamlit) - Recommended for Most Users

The easiest way to use the agent is through the interactive Streamlit UI:

#### Quick Start
```bash
python run_ui.py
```

Or directly with Streamlit:
```bash
streamlit run streamlit_app.py
```

The UI will open in your browser at `http://localhost:8501`

**Features:**
- 🎯 Drag-and-drop file upload
- 📊 Real-time workflow visualization
- 🎭 n8n-style node visualization
- 📥 Download results and reports
- ⚙️ Configure parameters interactively
- 📱 Responsive design

See [STREAMLIT_GUIDE.md](STREAMLIT_GUIDE.md) for detailed UI documentation.

### 💻 Python API - For Scripts and Automation

#### Basic Example

```python
from verilog_agent import VerilogVerificationAgent
from config import Config

# Initialize the agent
agent = VerilogVerificationAgent(
    api_key=Config.GOOGLE_API_KEY,
    max_iterations=5
)

# Your Verilog code
verilog_code = """
module counter_4bit (
    input wire clk,
    input wire reset,
    output reg [3:0] count
);

always @(posedge clk or posedge reset) begin
    if (reset)
        count <= 4'b0000;
    else
        count <= count + 1;
end

endmodule
"""


# Run verification
final_state = agent.run(
    datasheet_path="74HC00_datasheet.pdf",
    verilog_code=verilog_code
)

# Save the report
agent.save_report(final_state, "verification_report.md")
```

### Run the Example Script

```bash
python example_usage.py
```

### Reading from Files

```python
# Read Verilog from file
with open("my_design.v", 'r') as f:
    verilog_code = f.read()

# Run verification
final_state = agent.run(
    datasheet_path="my_component_datasheet.pdf",
    verilog_code=verilog_code
)

# Save report
agent.save_report(final_state, "my_report.md")
```

## How It Works

### 1. **Datasheet Analysis**
   - Analyzes the component datasheet to understand:
     - Component specifications
     - Pin configuration
     - Functional behavior
     - Timing requirements
   - Analyzes Verilog code structure and hierarchy

### 2. **Issue Identification**
   - Compares datasheet specifications with code implementation
   - Identifies:
     - Specification mismatches
     - Syntax errors
     - Logic errors
     - Timing issues
     - Best practice violations

### 3. **Iterative Fixing**
   - Applies suggested fixes to the code
   - Verifies each fix
   - Continues until:
     - All issues resolved, OR
     - Maximum iterations reached

### 4. **Report Generation**
   - Creates comprehensive report including:
     - Executive summary
     - Detailed analysis
     - Issues found and resolved
     - Verification results
     - Code quality assessment
     - Recommendations

## Configuration

### Agent Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `api_key` | Google Gemini API key | Required |
| `max_iterations` | Maximum fix iterations | 5 |
| `model` | Gemini model name | gemini-1.5-pro |
| `temperature` | Model temperature | 0.2 |

### Environment Variables

- `GOOGLE_API_KEY`: Your Google API key (required)
- `MAX_ITERATIONS`: Maximum number of fix iterations (default: 5)
- `LOG_LEVEL`: Logging level (default: INFO)

## Output

The agent generates:

1. **Console Output**: Real-time progress and findings
2. **Markdown Report**: Comprehensive verification report
3. **Fixed Code**: Corrected Verilog code (if issues found)

### Example Report Structure

```markdown
# VERILOG DESIGN VERIFICATION REPORT

Generated: 2026-02-28 10:30:00
Design Image: design_schematic.png
Iterations: 2
Status: verified

## 1. EXECUTIVE SUMMARY
...

## 2. DESIGN ANALYSIS
...

## 3. ISSUES IDENTIFIED AND RESOLVED
...

## 4. VERIFICATION RESULTS
...

## 5. FINAL CODE QUALITY ASSESSMENT
...

## 6. RECOMMENDATIONS
...

## 7. CONCLUSION
...

## FINAL VERIFIED CODE
```verilog
// Fixed code here
```
```

## Project Structure

```
Self-Rectification-Agentic-AI/
├── 🎯 Core Agent
│   ├── verilog_agent.py              # Main LangGraph agent implementation
│   ├── config.py                     # Configuration management
│   └── workflow_visualizer.py        # Workflow visualization utilities
│
├── 🎨 Web UI (Streamlit)
│   ├── streamlit_app.py              # Main Streamlit application
│   ├── run_ui.py                     # Launcher script
│   └── .streamlit/
│       └── config.toml               # Streamlit configuration
│
├── 🐳 Deployment
│   ├── Dockerfile                    # Docker container definition
│   └── docker-compose.yml            # Docker Compose orchestration
│
├── 📚 Documentation
│   ├── README.md                     # This file
│   ├── QUICK_START.md                # 5-minute getting started
│   ├── STREAMLIT_GUIDE.md            # Web UI documentation
│   └── DESIGN_IMAGE_GUIDE.md         # Guide for design images
│
├── 🔧 Examples & Config
│   ├── example_usage.py              # Python API examples
│   ├── sample_design.v               # Sample Verilog code
│   ├── requirements.txt              # Python dependencies
│   ├── .env.example                  # Environment variables template
│   └── .gitignore                    # Git ignore rules
```

## Requirements

- Python 3.8+
- Google Gemini API key
- Internet connection (for API calls)


## Dependencies

- `langgraph` - For agent workflow orchestration
- `langchain` - For LLM integrations
- `langchain-google-genai` - Gemini integration
- `google-genai` - Google AI SDK (new package, replaces deprecated google-generativeai)
- `Pillow` - Image processing
- `python-dotenv` - Environment management
- `pydantic` - Data validation

## Limitations

- Requires valid design images for full functionality
- API rate limits apply (Gemini API)
- Complex designs may require more iterations
- Best suited for RTL-level Verilog code
- Does not perform functional simulation

## Deployment

### Docker Deployment

Deploy the Streamlit UI using Docker:

```bash
# Build the image
docker build -t verilog-agent .

# Run with environment variables
docker run -p 8501:8501 \
  -e GOOGLE_API_KEY=your_api_key \
  verilog-agent
```

### Docker Compose

For easier management:

```bash
# Set your API key in .env file
cp .env.example .env
# Edit .env with your API key

# Start the service
docker-compose up

# Access at http://localhost:8501
```

### Cloud Deployment

**Streamlit Cloud:**
```bash
streamlit deploy
```

Follow the prompts to connect your GitHub repository to Streamlit Cloud.

### Environment Variables

For deployment, ensure these are set:
- `GOOGLE_API_KEY`: Your Google Gemini API key (required)
- `MAX_ITERATIONS`: Maximum fix iterations (default: 5)
- `LOG_LEVEL`: Logging level (default: INFO)

## Future Enhancements

- [ ] Integration with Verilog simulators (iverilog, ModelSim)
- [ ] Support for SystemVerilog
- [ ] Automated testbench generation
- [ ] Timing analysis integration
- [ ] Support for multiple design images
- [ ] Interactive mode with user feedback
- [ ] Custom rule definitions
- [ ] Integration with synthesis tools

## Troubleshooting

### API Key Issues

```
ValueError: GOOGLE_API_KEY not found
```

**Solution**: Ensure your `.env` file contains a valid `GOOGLE_API_KEY`

### Image Not Found

```
Error analyzing image: [Errno 2] No such file or directory
```

**Solution**: Verify the image path is correct and the file exists

### Rate Limit Exceeded

**Solution**: Wait and retry, or upgrade your Gemini API quota

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

[Specify your license here]

## Acknowledgments

- Built with [LangGraph](https://github.com/langchain-ai/langgraph)
- Powered by [Google Gemini](https://deepmind.google/technologies/gemini/)
- Inspired by the need for automated hardware verification

## Contact

For questions or support, please [open an issue](link-to-issues).

---

**Note**: This agent is a verification assistant and should not replace thorough testing and formal verification methods for production hardware designs.
