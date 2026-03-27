"""
Verilog Design Verification Agent using LangGraph and Gemini
This agent iteratively analyzes component datasheets and Verilog code to identify issues,
fix them, and generate comprehensive reports.
"""

import os
from typing import TypedDict, Annotated, List, Optional
from datetime import datetime
from pathlib import Path
import time

from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from google import genai
from waveform_generator import WaveformGenerator
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


class AgentState(TypedDict):
    """State of the Verilog verification agent"""
    datasheet_path: str
    datasheet_content: str
    verilog_code: str
    current_code: str
    iteration: int
    max_iterations: int
    issues_found: List[dict]
    fixes_applied: List[dict]
    analysis_history: List[str]
    compiler_history: List[dict]
    last_compiler_check: dict
    llm_call_metrics: List[dict]
    llm_latency_summary: dict
    final_report: str
    status: str  # 'analyzing', 'fixing', 'verified', 'failed'
    design_image_path: Optional[str]
    simulator: str
    llm_latency_profile: str


class VerilogVerificationAgent:
    """
    LangGraph-based agent for Verilog design verification using Gemini
    """
    
    def __init__(
        self,
        api_key: str,
        max_iterations: int = 5,
        simulator: str = "Icarus Verilog",
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.2,
        llm_latency_profile: str = "balanced",
    ):
        """
        Initialize the Verilog Verification Agent
        
        Args:
            api_key: Google API key for Gemini
            max_iterations: Maximum number of fix iterations
        """
        self.api_key = api_key
        self.max_iterations = max_iterations
        self.simulator = simulator
        self.llm_latency_profile = llm_latency_profile.lower().strip() or "balanced"
        
        # Configure Gemini with new API
        self.client = genai.Client(api_key=api_key)
        
        # Initialize Gemini model
        self.model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature
        )
        
        # Build the graph
        self.workflow = self._build_graph()
        self.app = self.workflow.compile()

    def _latency_target_ms(self, profile: str) -> int:
        profile_l = (profile or "balanced").lower()
        if profile_l == "fast":
            return 2500
        if profile_l == "deep":
            return 9000
        return 5000

    def _invoke_model(self, prompt: str, state: Optional[AgentState], stage: str) -> str:
        started = time.perf_counter()
        response = self.model.invoke(prompt).content
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if state is not None:
            state["llm_call_metrics"].append(
                {
                    "stage": stage,
                    "latency_ms": elapsed_ms,
                    "timestamp": datetime.now().isoformat(),
                }
            )

        return response

    def _update_latency_summary(self, state: AgentState) -> None:
        metrics = state.get("llm_call_metrics", [])
        target_ms = self._latency_target_ms(state.get("llm_latency_profile", self.llm_latency_profile))

        if not metrics:
            state["llm_latency_summary"] = {
                "profile": state.get("llm_latency_profile", self.llm_latency_profile),
                "target_ms": target_ms,
                "calls": 0,
                "avg_ms": 0,
                "max_ms": 0,
                "total_ms": 0,
                "within_target_calls": 0,
                "within_target_rate": 0,
                "meets_target": True,
            }
            return

        latencies = [int(m.get("latency_ms", 0)) for m in metrics]
        total_ms = sum(latencies)
        calls = len(latencies)
        avg_ms = int(total_ms / calls) if calls else 0
        max_ms = max(latencies) if latencies else 0
        within_target = sum(1 for x in latencies if x <= target_ms)
        within_rate = round((within_target / calls) * 100, 1) if calls else 0.0

        state["llm_latency_summary"] = {
            "profile": state.get("llm_latency_profile", self.llm_latency_profile),
            "target_ms": target_ms,
            "calls": calls,
            "avg_ms": avg_ms,
            "max_ms": max_ms,
            "total_ms": total_ms,
            "within_target_calls": within_target,
            "within_target_rate": within_rate,
            "meets_target": bool(within_rate >= 80.0),
        }

    def _is_analog_code(self, verilog_code: str) -> bool:
        lower = verilog_code.lower()
        return (
            "`include \"disciplines.vams\"" in lower
            or "analog begin" in lower
            or "electrical " in lower
            or "<+" in verilog_code
        )

    def _resolve_iteration_simulator(self, state: AgentState) -> str:
        preferred = state.get("simulator", self.simulator)
        if self._is_analog_code(state["current_code"]):
            return "ngspice"
        if preferred == "Ngspice":
            return "ngspice"
        return "iverilog"

    def _run_compiler_checks(self, state: AgentState) -> dict:
        """Run syntax + compile checks every iteration using selected simulator."""
        sim_type = self._resolve_iteration_simulator(state)
        waveform_gen = WaveformGenerator(simulator=sim_type)

        syntax_ok, syntax_msg = waveform_gen.check_syntax(state["current_code"])
        compile_ok = False
        compile_msg = "Compile skipped because syntax failed"

        if syntax_ok:
            compile_ok, compile_msg = waveform_gen.compile_verilog(state["current_code"])

        waveform_gen.cleanup()

        return {
            "iteration": state["iteration"],
            "simulator": sim_type,
            "syntax_ok": syntax_ok,
            "syntax_msg": syntax_msg,
            "compile_ok": compile_ok,
            "compile_msg": compile_msg,
            "passed": bool(syntax_ok and compile_ok),
            "timestamp": datetime.now().isoformat(),
        }
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("analyze_design", self.analyze_design)
        workflow.add_node("identify_issues", self.identify_issues)
        workflow.add_node("fix_issues", self.fix_issues)
        workflow.add_node("verify_fixes", self.verify_fixes)
        workflow.add_node("generate_report", self.generate_report)
        
        # Define edges
        workflow.set_entry_point("analyze_design")
        workflow.add_edge("analyze_design", "identify_issues")
        
        # Conditional edge from identify_issues
        workflow.add_conditional_edges(
            "identify_issues",
            self.should_fix_issues,
            {
                "fix": "fix_issues",
                "verify": "verify_fixes"
            }
        )
        
        workflow.add_edge("fix_issues", "verify_fixes")
        
        # Conditional edge from verify_fixes
        workflow.add_conditional_edges(
            "verify_fixes",
            self.should_continue_iteration,
            {
                "continue": "identify_issues",
                "finish": "generate_report"
            }
        )
        
        workflow.add_edge("generate_report", END)
        
        return workflow
    
    def _extract_datasheet_content(self, datasheet_path: str) -> str:
        """Extract text content from PDF or text datasheet"""
        try:
            file_ext = Path(datasheet_path).suffix.lower()
            
            if file_ext == '.pdf':
                # Extract text from PDF
                if PdfReader is None:
                    return "Error: pypdf library not installed. Install with: pip install pypdf"
                
                reader = PdfReader(datasheet_path)
                text_content = []
                for page in reader.pages:
                    text_content.append(page.extract_text())
                return "\n".join(text_content)
            
            elif file_ext in ['.txt', '.md']:
                # Read text file
                with open(datasheet_path, 'r', encoding='utf-8') as f:
                    return f.read()
            
            else:
                return f"Unsupported file format: {file_ext}. Use .pdf, .txt, or .md"
                
        except Exception as e:
            return f"Error reading datasheet: {str(e)}"
    
    def _analyze_datasheet(self, datasheet_content: str) -> str:
        """Use Gemini to analyze the component datasheet"""
        try:
            prompt = f"""
            Analyze this component datasheet and extract key specifications:
            
            1. Component name and type
            2. Pin configuration and descriptions
            3. Electrical specifications (voltage, current, timing, etc.)
            4. Functional description and operation modes
            5. Truth tables or state diagrams if available
            6. Timing diagrams and constraints
            7. Interface protocols and signals
            8. Key design requirements and limitations
            
            Datasheet Content:
            {datasheet_content[:15000]}  # Limit to avoid token limits
            
            Provide a detailed technical summary focusing on aspects relevant to Verilog implementation.
            """
            
            response = self._invoke_model(prompt, None, "analyze_datasheet")
            return response
            
        except Exception as e:
            return f"Error analyzing datasheet: {str(e)}"
    
    def analyze_design(self, state: AgentState) -> AgentState:
        """Analyze the component datasheet and Verilog code"""
        print(f"\n{'='*60}")
        print("STEP 1: Analyzing Datasheet & Code")
        print(f"{'='*60}")
        
        # Extract and analyze datasheet
        datasheet_content = state["datasheet_content"]
        if not datasheet_content:
            datasheet_content = self._extract_datasheet_content(state["datasheet_path"])
            state["datasheet_content"] = datasheet_content

        # Single LLM call: analyze datasheet and RTL together to reduce latency.
        combined_prompt = f"""
        Analyze the following datasheet and Verilog code together and produce one unified report.

        Include these sections:
        1. DATASHEET ANALYSIS
           - Component name/type
           - Pin/config overview
           - Key electrical/timing constraints
           - Required behaviors for implementation

        2. CODE STRUCTURE ANALYSIS
           - Module hierarchy/interfaces
           - Functionality implemented
           - Design pattern/style observations

        3. DESIGN-CODE ALIGNMENT SUMMARY
           - Major matches
           - Potential mismatches
           - Risks to verify in later steps

        Datasheet Content:
        {datasheet_content[:15000]}

        Verilog Code:
        ```verilog
        {state["verilog_code"]}
        ```
        """

        combined_analysis = self._invoke_model(combined_prompt, state, "analyze_design")
        
        state["analysis_history"].append(combined_analysis)
        state["status"] = "analyzing"
        
        print("Datasheet and code analysis completed.")
        
        return state
    
    def identify_issues(self, state: AgentState) -> AgentState:
        """Identify issues by comparing design and code"""
        print(f"\n{'='*60}")
        print(f"STEP 2: Identifying Issues (Iteration {state['iteration']})")
        print(f"{'='*60}")
        
        # Get the latest analysis
        latest_analysis = state["analysis_history"][-1]
        
        waveform_context = ""
        if state.get("design_image_path"):
            waveform_context = "\n\nNote: A waveform diagram is available showing the signal behavior. Consider timing and signal transitions when identifying issues."

        compiler_context = ""
        if state.get("last_compiler_check"):
            c = state["last_compiler_check"]
            compiler_context = f"""

        Compiler/Simulator Validation (Iteration {c.get('iteration', state['iteration'])}, simulator={c.get('simulator', 'unknown')}):
        - Syntax: {'PASS' if c.get('syntax_ok') else 'FAIL'}
        - Syntax Details: {c.get('syntax_msg', '')}
        - Compile/Netlist Build: {'PASS' if c.get('compile_ok') else 'FAIL'}
        - Compile Details: {c.get('compile_msg', '')}
        """
        
        prompt = f"""
        You are an expert hardware design verification engineer.
        
        Based on the datasheet analysis and Verilog code, identify any issues:
        
        Previous Analysis:
        {latest_analysis}
        
        Current Verilog Code:
        ```verilog
        {state["current_code"]}
        ```{waveform_context}{compiler_context}
        
        Identify:
        1. Mismatches between the datasheet specifications and code implementation
        2. Syntax errors in Verilog
        3. Logic errors or potential bugs
        4. Missing functionality
        5. Timing issues or race conditions
        6. Best practice violations
        7. Port mismatches or connectivity issues
        
        For EACH issue found, provide:
        - Issue type (mismatch/syntax/logic/timing/other)
        - Severity (critical/high/medium/low)
        - Description
        - Location in code (module name, line estimate)
        - Suggested fix
        
        Format your response as:
        ISSUES_FOUND: <number>
        
        ISSUE_1:
        Type: <type>
        Severity: <severity>
        Description: <description>
        Location: <location>
        Suggested Fix: <fix>
        
        [Continue for each issue]
        
        If no issues found, respond with:
        ISSUES_FOUND: 0
        """
        
        response = self._invoke_model(prompt, state, "identify_issues")
        
        # Parse issues
        issues = self._parse_issues(response)
        state["issues_found"] = issues
        
        print(f"Found {len(issues)} issue(s)")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. [{issue['severity']}] {issue['type']}: {issue['description'][:80]}...")
        
        return state
    
    def _parse_issues(self, response: str) -> List[dict]:
        """Parse issues from LLM response"""
        issues = []
        
        # Extract number of issues
        if "ISSUES_FOUND: 0" in response:
            return issues
        
        # Split by ISSUE_ markers
        issue_blocks = response.split("ISSUE_")[1:]  # Skip first empty split
        
        for block in issue_blocks:
            issue = {}
            lines = block.strip().split('\n')
            
            for line in lines:
                if line.startswith("Type:"):
                    issue["type"] = line.replace("Type:", "").strip()
                elif line.startswith("Severity:"):
                    issue["severity"] = line.replace("Severity:", "").strip()
                elif line.startswith("Description:"):
                    issue["description"] = line.replace("Description:", "").strip()
                elif line.startswith("Location:"):
                    issue["location"] = line.replace("Location:", "").strip()
                elif line.startswith("Suggested Fix:"):
                    issue["suggested_fix"] = line.replace("Suggested Fix:", "").strip()
            
            if issue:  # Only add if we extracted something
                issues.append(issue)
        
        return issues
    
    def should_fix_issues(self, state: AgentState) -> str:
        """Decide whether to fix issues or proceed to verification"""
        if len(state["issues_found"]) == 0:
            return "verify"
        return "fix"
    
    def fix_issues(self, state: AgentState) -> AgentState:
        """Apply fixes to the Verilog code"""
        print(f"\n{'='*60}")
        print("STEP 3: Fixing Issues")
        print(f"{'='*60}")
        
        if not state["issues_found"]:
            return state
        
        # Prepare issues summary
        issues_summary = "\n".join([
            f"{i+1}. [{issue['severity']}] {issue['type']}: {issue['description']}\n   Fix: {issue['suggested_fix']}"
            for i, issue in enumerate(state["issues_found"])
        ])
        
        prompt = f"""
        You are an expert Verilog developer. Fix the following issues in the code:
        
        ISSUES TO FIX:
        {issues_summary}
        
        CURRENT CODE:
        ```verilog
        {state["current_code"]}
        ```
        
        Provide the COMPLETE fixed Verilog code. Make sure:
        1. All issues are addressed
        2. Code syntax is correct
        3. Code is properly formatted
        4. Comments explain the fixes
        
        Respond ONLY with the fixed Verilog code, no explanations outside the code.
        """
        
        fixed_code = self._invoke_model(prompt, state, "fix_issues")
        
        # Extract code from markdown if present
        if "```verilog" in fixed_code:
            fixed_code = fixed_code.split("```verilog")[1].split("```")[0].strip()
        elif "```" in fixed_code:
            fixed_code = fixed_code.split("```")[1].split("```")[0].strip()
        
        state["current_code"] = fixed_code
        state["fixes_applied"].append({
            "iteration": state["iteration"],
            "issues_fixed": len(state["issues_found"]),
            "timestamp": datetime.now().isoformat()
        })
        
        print(f"Applied {len(state['issues_found'])} fix(es)")
        
        return state
    
    def verify_fixes(self, state: AgentState) -> AgentState:
        """Verify that fixes were applied correctly"""
        print(f"\n{'='*60}")
        print("STEP 4: Verifying Fixes")
        print(f"{'='*60}")
        
        state["iteration"] += 1

        compiler_result = self._run_compiler_checks(state)
        state["last_compiler_check"] = compiler_result
        state["compiler_history"].append(compiler_result)

        print(
            "Compiler checks:",
            f"syntax={'PASS' if compiler_result['syntax_ok'] else 'FAIL'},",
            f"compile={'PASS' if compiler_result['compile_ok'] else 'FAIL'}"
        )
        
        # Simple verification - check if code compiles and looks valid
        prompt = f"""
        Verify this Verilog code is:
        1. Syntactically correct
        2. Logically sound
        3. Follows best practices

        Compiler/Simulator Validation:
        - Simulator: {compiler_result['simulator']}
        - Syntax Result: {'PASS' if compiler_result['syntax_ok'] else 'FAIL'}
        - Syntax Message: {compiler_result['syntax_msg']}
        - Compile Result: {'PASS' if compiler_result['compile_ok'] else 'FAIL'}
        - Compile Message: {compiler_result['compile_msg']}
        
        Code:
        ```verilog
        {state["current_code"]}
        ```
        
        Respond with: VERIFIED or NEEDS_WORK.
        Rules:
        - If compiler/simulator validation failed, you MUST respond NEEDS_WORK.
        - Only respond VERIFIED when both compiler checks pass and no major logic issues remain.
        Provide brief explanation.
        """
        
        verification = self._invoke_model(prompt, state, "verify_fixes")
        
        if compiler_result["passed"] and "VERIFIED" in verification.upper():
            state["status"] = "verified"
            print("[OK] Code verified successfully")
        else:
            state["status"] = "needs_work"
            print("[WARN] Code needs more work")

        state["analysis_history"].append(
            (
                f"Iteration {state['iteration']} compiler check ({compiler_result['simulator']}): "
                f"syntax={'PASS' if compiler_result['syntax_ok'] else 'FAIL'}, "
                f"compile={'PASS' if compiler_result['compile_ok'] else 'FAIL'}.\n"
                f"Syntax message: {compiler_result['syntax_msg']}\n"
                f"Compile message: {compiler_result['compile_msg']}\n"
                f"LLM verification: {verification}"
            )
        )
        
        return state
    
    def should_continue_iteration(self, state: AgentState) -> str:
        """Decide whether to continue iterating or finish"""
        if state["status"] == "verified":
            return "finish"
        
        if state["iteration"] >= state["max_iterations"]:
            print(f"\n[WARN] Reached maximum iterations ({state['max_iterations']})")
            return "finish"
        
        return "continue"
    
    def generate_report(self, state: AgentState) -> AgentState:
        """Generate final verification report"""
        print(f"\n{'='*60}")
        print("STEP 5: Generating Final Report")
        print(f"{'='*60}")

        self._update_latency_summary(state)
        latency_summary = state.get("llm_latency_summary", {})
        
        prompt = f"""
        Generate a comprehensive Verilog design verification report.
        
        DESIGN ANALYSIS:
        {state["analysis_history"][0]}
        
        ITERATIONS PERFORMED: {state["iteration"]}
        FIXES APPLIED: {len(state["fixes_applied"])}
        FINAL STATUS: {state["status"]}
        COMPILER CHECKS RUN: {len(state.get("compiler_history", []))}
        LLM LATENCY PROFILE: {latency_summary.get("profile", self.llm_latency_profile)}
        LLM LATENCY TARGET (ms/call): {latency_summary.get("target_ms", self._latency_target_ms(self.llm_latency_profile))}
        LLM LATENCY AVG (ms/call): {latency_summary.get("avg_ms", 0)}
        LLM LATENCY MAX (ms/call): {latency_summary.get("max_ms", 0)}
        LLM LATENCY WITHIN TARGET: {latency_summary.get("within_target_rate", 0)}%
        
        FINAL CODE:
        ```verilog
        {state["current_code"]}
        ```
        
        Generate a detailed report including:
        
        1. EXECUTIVE SUMMARY
           - Overall design assessment
           - Verification status
           - Key findings
        
        2. DESIGN ANALYSIS
           - Image analysis summary
           - Code structure overview
           - Design-code alignment
        
        3. ISSUES IDENTIFIED AND RESOLVED
           - List all issues found across iterations
           - Fixes applied
           - Resolution status
        
        4. VERIFICATION RESULTS
           - Syntax verification
           - Logic verification
           - Design compliance
        
        5. FINAL CODE QUALITY ASSESSMENT
           - Code quality metrics
           - Best practices compliance
           - Areas for improvement
        
        6. RECOMMENDATIONS
           - Further testing needed
           - Potential enhancements
           - Deployment readiness
        
        7. CONCLUSION
        
        Format the report professionally with clear sections and bullet points.
        """
        
        report = self._invoke_model(prompt, state, "generate_report")
        state["final_report"] = report
        self._update_latency_summary(state)
        
        print("[OK] Report generated successfully")
        
        return state
    
    def run(self, datasheet_path: str, verilog_code: str, datasheet_content: str = "", design_image_path: str = None) -> dict:
        """
        Run the verification agent
        
        Args:
            datasheet_path: Path to the component datasheet (PDF or text)
            verilog_code: Verilog code as string
            datasheet_content: Pre-extracted datasheet content (optional)
            design_image_path: Path to waveform or design image (optional)
            
        Returns:
            Final state with report
        """
        print("\n" + "="*60)
        print("VERILOG DESIGN VERIFICATION AGENT")
        print("Powered by LangGraph + Gemini")
        print("="*60)
        
        # Initialize state
        initial_state = {
            "datasheet_path": datasheet_path,
            "datasheet_content": datasheet_content,
            "verilog_code": verilog_code,
            "current_code": verilog_code,
            "iteration": 0,
            "max_iterations": self.max_iterations,
            "issues_found": [],
            "fixes_applied": [],
            "analysis_history": [],
            "compiler_history": [],
            "last_compiler_check": {},
            "llm_call_metrics": [],
            "llm_latency_summary": {},
            "final_report": "",
            "status": "initializing",
            "design_image_path": design_image_path,
            "simulator": self.simulator,
            "llm_latency_profile": self.llm_latency_profile,
        }
        
        # Run the workflow
        final_state = self.app.invoke(initial_state)
        
        return final_state
    
    def save_report(self, state: dict, output_path: str):
        """Save the final report to a file"""
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# VERILOG DESIGN VERIFICATION REPORT\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"Datasheet: {state['datasheet_path']}\n")
            f.write(f"Iterations: {state['iteration']}\n")
            f.write(f"Status: {state['status']}\n")
            f.write("\n" + "="*80 + "\n\n")
            f.write(state['final_report'])
            f.write("\n\n" + "="*80 + "\n")
            f.write("## FINAL VERIFIED CODE\n\n")
            f.write("```verilog\n")
            f.write(state['current_code'])
            f.write("\n```\n")
        
        print(f"\n[OK] Report saved to: {output_path}")
