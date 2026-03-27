import { useState, useRef, useEffect } from 'react';
import type { ChangeEvent } from 'react';
import { 
  FileText, Code2, Activity, Settings, Upload, 
  Cpu, Zap, TestTube, AlertCircle, FileDigit,
  ArrowRight, ArrowLeft, Check, X,
  Moon, Sun
} from 'lucide-react';
import './index.css';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';



type VerificationState = {
  status: string;
  iteration: number;
  issues_found: any[];
  fixes_applied: any[];
  current_code: string;
  verilog_code: string;
  final_report: string;
};

const inferSimulatorMode = (code: string, message?: string): 'analog' | 'digital' => {
  const combined = `${code}\n${message || ''}`.toLowerCase();
  const looksAnalog =
    combined.includes('`include "disciplines.vams"') ||
    combined.includes('analog begin') ||
    combined.includes('electrical ') ||
    combined.includes('<+');

  return looksAnalog ? 'analog' : 'digital';
};

const parseApiResponse = async (res: Response) => {
  const raw = await res.text();
  if (!raw) {
    throw new Error(`HTTP ${res.status} ${res.statusText}`);
  }

  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${raw.slice(0, 200)}`);
  }

  if (!res.ok) {
    throw new Error(data?.message || `HTTP ${res.status} ${res.statusText}`);
  }

  return data;
};

function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [step, setStep] = useState(1);
  const [maxIterations, setMaxIterations] = useState(5);

  const [datasheet, setDatasheet] = useState<File | null>(null);
  const [verilogCode, setVerilogCode] = useState('');
  
  const [availableSims, setAvailableSims] = useState<string[]>(['Icarus Verilog', 'Ngspice']);
  const [selectedSim, setSelectedSim] = useState('Ngspice');
  const [simulatorMode, setSimulatorMode] = useState<'analog' | 'digital' | null>(null);
  
  const [waveformImage, setWaveformImage] = useState<string | null>(null);
  
  // Action tracking
  const [isCheckingSyntax, setIsCheckingSyntax] = useState(false);
  const [syntaxMessage, setSyntaxMessage] = useState('');
  
  const [isCompiling, setIsCompiling] = useState(false);
  const [compileMessage, setCompileMessage] = useState('');
  
  const [isVerifying, setIsVerifying] = useState(false);
  const [verificationState, setVerificationState] = useState<VerificationState | null>(null);
  const [verifyMessage, setVerifyMessage] = useState('');
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.body.className = theme;
  }, [theme]);

  useEffect(() => {
    fetch(`${API_BASE}/status`)
      .then(res => parseApiResponse(res))
      .then(data => {
        if (data.available) setAvailableSims(data.available);
        if (data.available && data.available.length > 0) {
          setSelectedSim(data.available[0]);
        }
      })
      .catch(err => console.error("Failed to fetch simulator status", err));
  }, []);

  const handleDatasheetUpload = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setDatasheet(e.target.files[0]);
    }
  };

  const nextStep = () => setStep(s => Math.min(s + 1, 4));
  const prevStep = () => setStep(s => Math.max(s - 1, 1));

  const handleSyntaxCheck = async () => {
    setIsCheckingSyntax(true);
    setSyntaxMessage('');
    try {
      const res = await fetch(`${API_BASE}/syntax`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verilog_code: verilogCode,
          simulator: selectedSim,
          xyce_path: undefined
        })
      });
      const data = await parseApiResponse(res);
      if (data.success) {
        const mode = inferSimulatorMode(verilogCode, data.message);
        setSimulatorMode(mode);
        const forcedSim = mode === 'analog' ? 'Ngspice' : 'Icarus Verilog';
        if (availableSims.includes(forcedSim)) {
          setSelectedSim(forcedSim);
        }
        setSyntaxMessage("✅ Syntax verified successfully.");
      } else {
        const mode = inferSimulatorMode(verilogCode, data.message);
        setSimulatorMode(mode);
        const forcedSim = mode === 'analog' ? 'Ngspice' : 'Icarus Verilog';
        if (availableSims.includes(forcedSim)) {
          setSelectedSim(forcedSim);
        }
        setSyntaxMessage(`❌ Syntax Error: ${data.message} \\n${data.error_msg || ''}`);
      }
    } catch(err) {
      setSyntaxMessage("❌ Request failed to connect.");
    } finally {
      setIsCheckingSyntax(false);
    }
  };

  const handleCompile = async () => {
    setIsCompiling(true);
    setCompileMessage('');
    setWaveformImage(null);
    try {
      const res = await fetch(`${API_BASE}/compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verilog_code: verilogCode,
          simulator: selectedSim,
          xyce_path: undefined
        })
      });
      const data = await parseApiResponse(res);
      if (data.success) {
        setCompileMessage("✅ Compilation complete.");
        if (data.image_path) {
          setWaveformImage(`${API_BASE}/image?path=${encodeURIComponent(data.image_path)}`);
        }
      } else {
        setCompileMessage(`❌ Compilation Error: ${data.message} \\n${data.error_msg || ''}`);
      }
    } catch (err) {
      setCompileMessage("❌ Request failed.");
    } finally {
      setIsCompiling(false);
    }
  };

  const handleVerify = async () => {
    setIsVerifying(true);
    setVerifyMessage('');
    setVerificationState(null);
    try {
      const formData = new FormData();
      if (datasheet) formData.append('datasheet', datasheet);
      formData.append('verilog_code', verilogCode);
      formData.append('max_iterations', maxIterations.toString());
      formData.append('model_name', 'gemini-2.5-flash');
      formData.append('temperature', '0.2');
      
      const res = await fetch(`${API_BASE}/verify`, { method: 'POST', body: formData });

      const data = await parseApiResponse(res);

      if (!res.ok || !data.success) {
        throw new Error(data.message || "Verification task failed on server.");
      }
      
      setVerificationState(data.state);
      setVerifyMessage("✅ Automated patching process wrapped up successfully.");
      
    } catch (err: any) {
      setVerifyMessage("❌ Error: " + err.message);
    } finally {
      setIsVerifying(false);
    }
  };

  // Rendering individual pages to keep structure clean
  const renderPage1 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '3rem'}}>
        <h1>Initialize Verification Protocol</h1>
        <p>1. Target Architecture Specifications</p>
      </div>

      <div className="card glass-panel upload-zone" onClick={() => fileInputRef.current?.click()}>
        <input type="file" ref={fileInputRef} onChange={handleDatasheetUpload} accept=".txt,.md,.pdf" style={{display: 'none'}} />
        {datasheet ? (
          <>
            <FileDigit size={48} className="text-secondary" />
            <h3>{datasheet.name}</h3>
            <p className="text-muted">{(datasheet.size / 1024).toFixed(1)} KB recognized. Perfect.</p>
          </>
        ) : (
          <>
            <Upload size={48} className="text-primary" style={{opacity: 0.8}} />
            <h3>Upload Hardware Datasheet</h3>
            <p className="text-muted">Supply your technical constraints via PDF, Word, or TXT formats.</p>
          </>
        )}
      </div>

      <div className="card glass-panel" style={{marginTop: '2rem', maxWidth: '600px', margin: '2rem auto'}}>
        <div className="card-title"><Settings /> Agent Options & Iteration Manager Configuration</div>
        <div className="config-group">
          <label><span>Auto-Correction Passes (Depth)</span> <span className="text-primary">{maxIterations}</span></label>
          <input type="range" min="1" max="10" value={maxIterations} onChange={e => setMaxIterations(parseInt(e.target.value))} />
        </div>
      </div>
    </div>
  );

  const renderPage2 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '2rem'}}>
        <h1>Design Input</h1>
        <p>2. Hardware Description Language Source</p>
      </div>

      <div className="card glass-panel" style={{marginBottom: '2rem'}}>
        <div className="card-title"><Code2 /> Verilog Editor</div>
        <textarea 
          className="code-editor"
          value={verilogCode}
          onChange={e => setVerilogCode(e.target.value)}
          placeholder="module your_circuit (\\n  input wire clk,\\n  output wire status\\n);\\n\\nendmodule"
          spellCheck="false"
          style={{height: '350px'}}
        />
      </div>
    </div>
  );

  const renderPage3 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '3rem'}}>
        <h1>Execution Pipeline</h1>
        <p>3. Simulate, Compile, and Validate</p>
      </div>

      <div className="pipeline-container">
        {/* Step A: Syntax */}
        <div className="pipeline-action glass-panel card">
          <div className="card-title"><FileText /> Syntax Check</div>
          <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Perform rapid syntactic analysis omitting linking overhead.</p>
          <button className="btn btn-secondary w-full" onClick={handleSyntaxCheck} disabled={isCheckingSyntax}>
             {isCheckingSyntax ? "Checking..." : "Verify Syntax"}
          </button>
          {syntaxMessage && <div className="status-msg" style={{color: syntaxMessage.includes('❌') ? 'var(--danger)' : 'var(--success)'}}>{syntaxMessage}</div>}
        </div>

        {/* Step B: Compile */}
        <div className="pipeline-action glass-panel card">
          <div className="card-title"><Cpu /> Compile Hierarchy</div>
          <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Elaborate top-level designs into binary instructions.</p>
          
          <div className="sim-radio-group" style={{gap: '0.5rem', flexWrap:'wrap'}}>
            {availableSims.map(s => (
              <label
                key={s}
                className="sim-radio"
                style={{
                  opacity: simulatorMode === 'analog' && s === 'Icarus Verilog' ? 0.45 : 1,
                  cursor: simulatorMode === 'analog' && s === 'Icarus Verilog' ? 'not-allowed' : 'pointer'
                }}
              >
                <input
                  type="radio"
                  name="simulator"
                  value={s}
                  checked={selectedSim === s}
                  onChange={e => setSelectedSim(e.target.value)}
                  disabled={simulatorMode === 'analog' && s === 'Icarus Verilog'}
                />
                <span style={{fontSize: '0.85rem'}}>{s}</span>
              </label>
            ))}
          </div>

          <button className="btn btn-secondary w-full" onClick={handleCompile} disabled={isCompiling}>
             {isCompiling ? "Compiling..." : "Compile Object"}
          </button>
          {compileMessage && <div className="status-msg" style={{color: compileMessage.includes('❌') ? 'var(--danger)' : 'var(--success)'}}>{compileMessage}</div>}
        </div>

        {/* Step C: Waveform */}
        <div className="pipeline-action glass-panel card">
          <div className="card-title"><Activity /> Generate Waveform</div>
          <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Execute testbench loops to render visualization. (Requires Compile first).</p>
          {waveformImage ? (
             <button className="btn btn-secondary w-full" onClick={() => window.open(waveformImage, '_blank')}>View Captured Trace</button>
          ) : (
             <button className="btn btn-secondary w-full" disabled>Trace Unavailable</button>
          )}
        </div>

        {/* Step D: Agent */}
        <div className="pipeline-action glass-panel card">
          <div className="card-title"><Zap /> Validate AI Target</div>
          <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Initiate autonomous iteration & correction protocol against uploaded spec.</p>
          <button className="btn w-full" onClick={handleVerify} disabled={isVerifying || !datasheet}>
             {isVerifying ? <><TestTube className="animate-spin" /> Iterating...</> : "Execute Delta Analysis"}
          </button>
          {verifyMessage && <div className="status-msg" style={{color: verifyMessage.includes('❌') ? 'var(--danger)' : 'var(--success)'}}>{verifyMessage}</div>}
        </div>
      </div>
    </div>
  );

  const renderPage4 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '3rem'}}>
        <h1>Resolution Delta</h1>
        <p>4. Assessment & Commits</p>
      </div>

      {!verificationState ? (
        <div className="card glass-panel text-center">
            <h3>No Active Verification Data</h3>
            <p className="text-muted">Return to the Execution Pipeline strictly to run Delta Analysis.</p>
        </div>
      ) : (
        <div className="results-wizard">
          {verificationState.issues_found && verificationState.issues_found.length > 0 && (
              <div className="card glass-panel" style={{borderColor: 'var(--issue-bg)', marginBottom: '2rem'}}>
                <div className="card-title" style={{color: 'var(--issue-accent)'}}><AlertCircle /> Validation Issues Discovered</div>
                <div style={{marginTop: '1.5rem'}}>
                  {verificationState.issues_found.map((issue, idx) => (
                    <div key={idx} className="issue-card">
                      <div className="issue-header">
                        <span className="issue-badge">{issue.severity}</span>
                        <strong style={{fontSize: '1.1rem'}}>{issue.type}</strong>
                      </div>
                      <div className="issue-desc">{issue.description}</div>
                      <div className="issue-meta">
                        <div><strong>Origin:</strong> {issue.location}</div>
                        <div><strong>Agent Resolution:</strong> {issue.suggested_fix}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
          )}

          <div className="card glass-panel diff-container view-diff">
            <div className="diff-pane">
              <h4>Original Master</h4>
              <textarea className="code-editor" readOnly value={verificationState.verilog_code} />
            </div>
            <div className="diff-pane">
              <h4>Artificial Correction</h4>
              <textarea className="code-editor patch-pane" readOnly value={verificationState.current_code} />
            </div>
          </div>

          <div style={{display: 'flex', gap: '1rem', marginTop: '2rem'}}>
             <button className="btn success w-full" onClick={() => {
                 setVerilogCode(verificationState.current_code);
                 setVerificationState(null);
                 setVerifyMessage('');
                 setStep(2);
             }}>
                 <Check /> Accept Patch & Return to Editor
             </button>
             <button className="btn danger w-full" onClick={() => {
                 setVerificationState(null);
                 setVerifyMessage('');
                 setStep(2);
             }}>
                 <X /> Reject Changes & Edit Manually
             </button>
          </div>

          <div className="card glass-panel" style={{marginTop: '2.5rem'}}>
            <div className="card-title">Analysis Execution Log</div>
            <div className="code-editor" style={{height: '300px', whiteSpace: 'pre-wrap', border: 'none', background: 'var(--report-bg)'}}>
              {verificationState.final_report}
            </div>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="app-container layout-wizard">
       <nav className="wizard-stepper glass-panel">
         <div className="brand" style={{marginBottom: '2rem', justifyContent: 'center'}}>
           <Cpu /> Verilog Agent
         </div>
         <ul className="stepper-list">
           <li className={step >= 1 ? 'active' : ''} onClick={() => setStep(1)}>1. Hardware Spec</li>
           <li className={step >= 2 ? 'active' : ''} onClick={() => setStep(2)}>2. System Design</li>
           <li className={step >= 3 ? 'active' : ''} onClick={() => setStep(3)}>3. Workflow Pipeline</li>
           <li className={step >= 4 ? 'active' : ''} onClick={() => setStep(4)}>4. Analysis Audit</li>
         </ul>
         
         <div style={{marginTop: 'auto', display: 'flex', justifyContent: 'center'}}>
            <button 
              className="btn btn-secondary w-full" 
              onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}
              style={{justifyContent: 'center'}}
            >
              {theme === 'dark' ? <><Sun size={18}/> Light Mode</> : <><Moon size={18}/> Dark Mode</>}
            </button>
         </div>
       </nav>

       <main className="wizard-content">
          <div className="wizard-body">
             {step === 1 && renderPage1()}
             {step === 2 && renderPage2()}
             {step === 3 && renderPage3()}
             {step === 4 && renderPage4()}
          </div>

          <footer className="wizard-footer glass-panel">
             <button className="btn btn-secondary" disabled={step === 1} onClick={prevStep}>
                <ArrowLeft size={18} /> Previous Sequence
             </button>
             <button 
               className="btn" 
               disabled={
                 step === 4 || 
                 (step === 1 && !datasheet) || 
                 (step === 2 && !verilogCode.trim())
               } 
               onClick={nextStep}
             >
                {step === 3 ? "Review Deltas" : "Proceed Form"} <ArrowRight size={18} />
             </button>
          </footer>
       </main>
    </div>
  );
}

export default App;
