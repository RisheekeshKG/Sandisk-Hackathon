import sys, io
# Force UTF-8 output on Windows (prevents UnicodeEncodeError with Unicode chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import tempfile
import subprocess
import shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from config import Config
from verilog_agent import VerilogVerificationAgent
from waveform_generator import WaveformGenerator

app = FastAPI(title="Verilog Verification API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def resolve_executable(cmd: str) -> Optional[str]:
    resolved = shutil.which(cmd)
    if resolved:
        return resolved

    common_paths = [
        f"/opt/homebrew/bin/{cmd}",
        f"/usr/local/bin/{cmd}",
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None


def check_simulator(cmd):
    return resolve_executable(cmd) is not None

@app.get("/api/status")
def get_status():
    iverilog = check_simulator("iverilog")
    ngspice = check_simulator("ngspice")
    
    available = []
    if iverilog: available.append("Icarus Verilog")
    if ngspice: available.append("Ngspice")
        
    return {
        "simulators": {
            "iverilog": iverilog,
            "ngspice": ngspice
        },
        "available": available
    }

class CompileRequest(BaseModel):
    verilog_code: str
    simulator: str
    xyce_path: Optional[str] = None

@app.post("/api/syntax")
def check_syntax(req: CompileRequest):
    sim_type = "iverilog" if req.simulator == "Icarus Verilog" else "ngspice"
    waveform_gen = WaveformGenerator(simulator=sim_type, xyce_path=req.xyce_path)
    success, msg = waveform_gen.check_syntax(req.verilog_code)
    waveform_gen.cleanup()
    return {"success": success, "message": msg}

@app.post("/api/compile")
def compile_verilog(req: CompileRequest):
    sim_type = "iverilog" if req.simulator == "Icarus Verilog" else "ngspice"
    waveform_gen = WaveformGenerator(simulator=sim_type, xyce_path=req.xyce_path)
    success, msg = waveform_gen.compile_verilog(req.verilog_code)
    
    # Generate waveform instantly
    if success:
        vcd_path, image_path, error_msg = waveform_gen.generate_waveform_from_sim()
        
        return {
            "success": True,
            "message": msg,
            "image_path": image_path,
            "error_msg": error_msg
        }
    return {"success": False, "message": msg}

@app.post("/api/verify")
async def verify_design(
    verilog_code: str = Form(...),
    max_iterations: int = Form(5),
    simulator: str = Form("Icarus Verilog"),
    model_name: str = Form("gemini-2.5-flash"),
    temperature: float = Form(0.2),
    llm_latency_profile: str = Form("balanced"),
    datasheet: UploadFile = File(None),
    image_path: str = Form(None)
):
    if not Config.GOOGLE_API_KEY:
        return JSONResponse(status_code=400, content={"success": False, "message": "Google API Key not found in environment. Please set GOOGLE_API_KEY."})
    
    datasheet_path = ""
    datasheet_content = ""
    
    if datasheet:
        file_ext = os.path.splitext(datasheet.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            content = await datasheet.read()
            tmp.write(content)
            datasheet_path = tmp.name
    else:
        return JSONResponse(status_code=400, content={"success": False, "message": "Datasheet is required. Please upload one."})

    # Initialize Agent
    try:
        agent = VerilogVerificationAgent(
            api_key=Config.GOOGLE_API_KEY,
            max_iterations=max_iterations,
            simulator=simulator,
            model_name=model_name,
            temperature=temperature,
            llm_latency_profile=llm_latency_profile,
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"Failed to initialize agent: {str(e)}"})

    try:
        final_state = agent.run(
            datasheet_path=datasheet_path,
            verilog_code=verilog_code,
            datasheet_content=datasheet_content,
            design_image_path=image_path if image_path and os.path.exists(image_path) else None
        )
        return {"success": True, "state": final_state}
    except Exception as e:
        import traceback
        return JSONResponse(status_code=500, content={"success": False, "message": f"Verification failed: {str(e)}\\n{traceback.format_exc()}"})
    
@app.get("/api/image")
def get_image(path: str):
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="Image not found")
