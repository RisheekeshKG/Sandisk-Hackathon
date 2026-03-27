"""
agent_runner.py
CI Agent Runner for Sandisk Hackathon backend.
Runs in GitHub Actions. Reads inputs from the repo, calls verilog_agent.py,
writes structured outputs, then commits them back via the GitHub API.
"""

import os
import json
import sys
import tempfile
import traceback
import difflib
import time
from datetime import datetime
from pathlib import Path

# ── Ensure project root on path ───────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from config import Config
from verilog_agent import VerilogVerificationAgent
from github_client import GitHubClient

def build_suggested_changes(original: str, fixed: str) -> str:
    """Return a unified diff of original vs fixed RTL."""
    if original.strip() == fixed.strip():
        return "// No changes suggested by the agent.\n"
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile="original.v",
        tofile="fixed.v",
    )
    return "".join(diff)

def build_report(run_id: str, state: dict, spec_filename: str, rtl_filename: str) -> dict:
    """Convert agent state into a structured JSON report."""
    issues = state.get("issues_found", [])
    fixes  = state.get("fixes_applied", [])

    critical = sum(1 for i in issues if i.get("severity", "").lower() == "critical")
    high     = sum(1 for i in issues if i.get("severity", "").lower() == "high")
    medium   = sum(1 for i in issues if i.get("severity", "").lower() == "medium")
    low      = sum(1 for i in issues if i.get("severity", "").lower() == "low")

    risk = "HIGH" if (critical + high) > 0 else ("MEDIUM" if medium > 0 else "LOW")

    return {
        "run_id":        run_id,
        "timestamp":     datetime.utcnow().isoformat(),
        "spec_file":     spec_filename,
        "rtl_file":      rtl_filename,
        "status":        state.get("status", "unknown"),
        "risk_level":    risk,
        "risk_counts":   {"critical": critical, "high": high, "medium": medium, "low": low},
        "issues":        issues,
        "fixes_applied": fixes,
        "iterations":    state.get("iteration", 0),
    }

def build_risk_summary(report: dict) -> str:
    """Human-readable risk summary text."""
    lines = [
        "VIGIL-AI Verification Risk Summary (Sandisk Hackathon)",
        f"Run: {report['run_id']}",
        f"Date: {report['timestamp']}",
        f"Spec: {report['spec_file']}",
        f"RTL : {report['rtl_file']}",
        "",
        f"Overall Risk Level : {report['risk_level']}",
        f"Status             : {report['status']}",
        f"Iterations         : {report['iterations']}",
        f"Issues Found       : {sum(report['risk_counts'].values())}",
        f"  CRITICAL : {report['risk_counts'].get('critical', 0)}",
        f"  HIGH     : {report['risk_counts']['high']}",
        f"  MEDIUM   : {report['risk_counts']['medium']}",
        f"  LOW      : {report['risk_counts']['low']}",
        "",
        "--- Issues ---",
    ]
    for i, issue in enumerate(report.get("issues", []), 1):
        lines.append(
            f"{i}. [{issue.get('severity','?').upper()}] "
            f"{issue.get('type','?')}: {issue.get('description','')}"
        )
        if issue.get("suggested_fix"):
            lines.append(f"   Fix: {issue['suggested_fix']}")
    return "\n".join(lines)

def main():
    print("=" * 60)
    print("VIGIL-AI Agent Runner (Sandisk Hackathon)")
    print("=" * 60)

    # ── Auth checks ────────────────────────────────────────────────────────────
    gh_token = os.getenv("GITHUB_TOKEN", "")
    if not gh_token:
        print("❌ GITHUB_TOKEN not set. Exiting.")
        sys.exit(1)

    google_key = os.getenv("GOOGLE_API_KEY", "")
    if not google_key:
        print("❌ GOOGLE_API_KEY not set. Add it as a repository secret.")
        sys.exit(1)

    # ── Read current_run.json from repo ────────────────────────────────────────
    gh = GitHubClient(token=gh_token)

    try:
        meta_file = gh._repo.get_contents("inputs/current_run.json")
        if isinstance(meta_file, list):
            meta_file = meta_file[0]
        meta = json.loads(meta_file.decoded_content.decode())
    except Exception as exc:
        print(f"❌ Could not read inputs/current_run.json: {exc}")
        sys.exit(1)

    run_id        = meta["run_id"]
    spec_filename = meta["spec_filename"]
    rtl_filename  = meta["rtl_filename"]

    print(f"Run ID      : {run_id}")
    print(f"Spec file   : {spec_filename}")
    print(f"RTL file    : {rtl_filename}")

    # ── Download input files ───────────────────────────────────────────────────
    try:
        spec_content = gh._repo.get_contents(f"inputs/spec/{spec_filename}")
        if isinstance(spec_content, list): spec_content = spec_content[0]
        spec_bytes = spec_content.decoded_content

        rtl_content = gh._repo.get_contents(f"inputs/rtl/{rtl_filename}")
        if isinstance(rtl_content, list): rtl_content = rtl_content[0]
        rtl_text = rtl_content.decoded_content.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"❌ Could not download input files: {exc}")
        sys.exit(1)

    # ── Write spec to a temp file (agent expects a file path) ─────────────────
    suffix = Path(spec_filename).suffix or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(spec_bytes)
        spec_tmp = tf.name

    logs = []
    def log(msg: str):
        print(msg)
        logs.append(msg)

    try:
        log(f"\n[{datetime.utcnow().isoformat()}] Starting verification agent...")
        
        agent = VerilogVerificationAgent(
            api_key=google_key,
            max_iterations=Config.MAX_ITERATIONS,
        )
        
        # We try to intercept 429 quota exhaustion specifically, just in case
        retries = 3
        state = None
        for attempt in range(retries):
            try:
                state = agent.run(
                    datasheet_path=spec_tmp,
                    datasheet_content="",
                    verilog_code=rtl_text,
                    design_image_path=None
                )
                break
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                    if attempt < retries - 1:
                        wait = (attempt + 1) * 30
                        log(f"⚠ API Rate limit hit. Waiting {wait}s before retry...")
                        time.sleep(wait)
                        continue
                raise

        log(f"[{datetime.utcnow().isoformat()}] Agent finished. Status: {state.get('status', 'unknown')}")

    except Exception as exc:
        error_msg = traceback.format_exc()
        log(f"❌ Agent error: {exc}\n{error_msg}")
        state = {
            "status": "error",
            "iteration": 0,
            "issues_found": [],
            "fixes_applied": [],
            "current_code": rtl_text,
            "verilog_code": rtl_text,
            "final_report": f"Agent failed: {exc}",
        }
    finally:
        try:
            os.unlink(spec_tmp)
        except Exception:
            pass

    # ── Build outputs ──────────────────────────────────────────────────────────
    report         = build_report(run_id, state, spec_filename, rtl_filename)
    risk_summary   = build_risk_summary(report)
    fixed_rtl      = state.get("current_code", rtl_text)
    suggested_diff = build_suggested_changes(
        state.get("verilog_code", rtl_text), fixed_rtl
    )
    final_report_md = state.get("final_report", "No report generated.")
    log_text        = "\n".join(logs)

    # ── Commit results ─────────────────────────────────────────────────────────
    log(f"\nCommitting results to verification_runs/{run_id}/...")

    files_to_commit = {
        f"input_spec{Path(spec_filename).suffix}": spec_bytes,
        "input_rtl.v":            rtl_text,
        "fixed_rtl.v":            fixed_rtl,
        "report.json":            json.dumps(report, indent=2),
        "risk_summary.txt":       risk_summary,
        "suggested_changes.v":    suggested_diff,
        "verification_report.md": final_report_md,
        "logs.txt":               log_text,
    }

    try:
        gh.commit_results(run_id, files_to_commit)
        log(f"✅ Results committed to verification_runs/{run_id}/")
    except Exception as exc:
        log(f"❌ Commit failed: {exc}\n{traceback.format_exc()}")
        sys.exit(1)

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"RUN COMPLETE: {run_id}")
    print(f"Risk Level  : {report['risk_level']}")
    print(f"Issues Found: {len(report['issues'])}")
    print(f"Status      : {report['status']}")
    print("=" * 60)

if __name__ == "__main__":
    main()
