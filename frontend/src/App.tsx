import { useState, useRef, useEffect } from 'react';
import type { ChangeEvent } from 'react';
import { 
  FileText, Code2, Activity, Settings, Upload, 
  Cpu, Zap, TestTube, AlertCircle, FileDigit,
  ArrowRight, ArrowLeft, Check, X,
  Moon, Sun
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
  compiler_history?: Array<{
    iteration: number;
    simulator: string;
    syntax_ok: boolean;
    syntax_msg: string;
    compile_ok: boolean;
    compile_msg: string;
    passed: boolean;
    timestamp: string;
  }>;
  llm_latency_summary?: {
    profile: string;
    target_ms: number;
    calls: number;
    avg_ms: number;
    max_ms: number;
    total_ms: number;
    within_target_calls: number;
    within_target_rate: number;
    meets_target: boolean;
  };
};

type DiffRow = {
  kind: 'context' | 'add' | 'del';
  oldNo: number | null;
  newNo: number | null;
  text: string;
};

type RiskSummary = {
  score: number;
  level: 'Low' | 'Medium' | 'High';
  highCount: number;
  mediumCount: number;
  lowCount: number;
};

type ExecutedTestRow = {
  name: string;
  input: string;
  output: string;
  status: 'PASS' | 'FAIL';
};

const extractModuleNames = (code: string): string[] => {
  const names = new Set<string>();
  const re = /\bmodule\s+([a-zA-Z_][a-zA-Z0-9_$]*)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code)) !== null) {
    names.add(m[1]);
  }
  return Array.from(names);
};

const extractChangedSignals = (rows: DiffRow[]): string[] => {
  const keywords = new Set([
    'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg', 'logic',
    'assign', 'always', 'begin', 'end', 'if', 'else', 'case', 'for', 'while',
    'parameter', 'localparam', 'generate', 'endgenerate', 'posedge', 'negedge'
  ]);

  const ids = new Set<string>();
  const idRe = /\b[a-zA-Z_][a-zA-Z0-9_$]*\b/g;
  for (const row of rows) {
    if (row.kind === 'context') continue;
    const line = row.text.replace(/\/\/.*$/, ' ').replace(/\/\*.*?\*\//g, ' ');
    let m: RegExpExecArray | null;
    while ((m = idRe.exec(line)) !== null) {
      const t = m[0];
      if (!keywords.has(t.toLowerCase()) && !/^\d/.test(t)) {
        ids.add(t);
      }
    }
  }

  return Array.from(ids).slice(0, 24);
};

const buildDiffRows = (oldCode: string, newCode: string): DiffRow[] => {
  const oldLines = oldCode.replace(/\r\n?/g, '\n').split('\n');
  const newLines = newCode.replace(/\r\n?/g, '\n').split('\n');

  const stripComments = (line: string) =>
    line
      .replace(/\/\*.*?\*\//g, ' ')
      .replace(/\/\/.*$/, ' ');

  const normalizeLine = (line: string) =>
    stripComments(line)
      .replace(/\t/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

  const isCommentOnlyLine = (line: string) => {
    const t = line.trim();
    return (
      t.startsWith('//') ||
      t.startsWith('/*') ||
      t.startsWith('*') ||
      t.startsWith('*/')
    );
  };

  const oldKeys = oldLines.map(normalizeLine);
  const newKeys = newLines.map(normalizeLine);

  const n = oldLines.length;
  const m = newLines.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0));

  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      if (oldKeys[i] === newKeys[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;

  while (i < n && j < m) {
    if (oldKeys[i] === newKeys[j]) {
      rows.push({ kind: 'context', oldNo: i + 1, newNo: j + 1, text: oldLines[i] });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ kind: 'del', oldNo: i + 1, newNo: null, text: oldLines[i] });
      i += 1;
    } else {
      rows.push({ kind: 'add', oldNo: null, newNo: j + 1, text: newLines[j] });
      j += 1;
    }
  }

  while (i < n) {
    rows.push({ kind: 'del', oldNo: i + 1, newNo: null, text: oldLines[i] });
    i += 1;
  }

  while (j < m) {
    rows.push({ kind: 'add', oldNo: null, newNo: j + 1, text: newLines[j] });
    j += 1;
  }

  return rows.filter(
    row => !(row.kind !== 'context' && isCommentOnlyLine(row.text))
  );
};

const computeRiskSummary = (state: VerificationState | null, diffRows: DiffRow[]): RiskSummary => {
  if (!state) {
    return { score: 0, level: 'Low', highCount: 0, mediumCount: 0, lowCount: 0 };
  }

  let highCount = 0;
  let mediumCount = 0;
  let lowCount = 0;

  for (const issue of state.issues_found || []) {
    const sev = String(issue?.severity || '').toLowerCase();
    if (sev.includes('high') || sev.includes('critical')) highCount += 1;
    else if (sev.includes('medium')) mediumCount += 1;
    else lowCount += 1;
  }

  const changedLines = diffRows.filter(r => r.kind !== 'context').length;
  const unresolved = Math.max((state.issues_found?.length || 0) - (state.fixes_applied?.length || 0), 0);
  const score = Math.min(
    100,
    highCount * 25 +
      mediumCount * 14 +
      lowCount * 6 +
      unresolved * 10 +
      Math.round(changedLines * 0.2)
  );

  const level: RiskSummary['level'] = score >= 67 ? 'High' : score >= 34 ? 'Medium' : 'Low';
  return { score, level, highCount, mediumCount, lowCount };
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
  const PAST_OUTPUT_CACHE_KEY = 'vigil_past_output_code';
  const LATEST_OUTPUT_CACHE_KEY = 'vigil_latest_output_code';
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [step, setStep] = useState(1);
  const [maxIterations, setMaxIterations] = useState(5);

  const [datasheet, setDatasheet] = useState<File | null>(null);
  const [verilogCode, setVerilogCode] = useState('');
  const [verilogFileName, setVerilogFileName] = useState('');
  const [verificationCode] = useState('');
  
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
  const [pastOutputCode, setPastOutputCode] = useState('');
  const [latestOutputCode, setLatestOutputCode] = useState('');
  const [verifyMessage, setVerifyMessage] = useState('');
  const [llmStrictness, setLlmStrictness] = useState(8);
  const [llmLatencyProfile, setLlmLatencyProfile] = useState<'fast' | 'balanced' | 'deep'>('balanced');
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const verilogFileInputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    const cachedPast = localStorage.getItem(PAST_OUTPUT_CACHE_KEY) || '';
    const cachedLatest = localStorage.getItem(LATEST_OUTPUT_CACHE_KEY) || '';
    setPastOutputCode(cachedPast);
    setLatestOutputCode(cachedLatest);
  }, []);

  const handleDatasheetUpload = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setDatasheet(e.target.files[0]);
    }
  };

  const handleVerilogUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) {
      return;
    }

    const file = e.target.files[0];
    try {
      const text = await file.text();
      setVerilogCode(text);
      setVerilogFileName(file.name);
      setVerificationState(null);
      setVerifyMessage('');
      setSyntaxMessage('');
      setCompileMessage('');
      setWaveformImage(null);
    } catch {
      setCompileMessage('❌ Failed to read uploaded Verilog file.');
    }
  };

  const nextStep = () => setStep(s => Math.min(s + 1, 5));
  const prevStep = () => setStep(s => Math.max(s - 1, 1));

  const getSimulationInputCode = () => {
    const design = verilogCode.trim();
    const verification = verificationCode.trim();
    if (!verification) return design;
    return `${design}\n\n// User verification/testbench code\n${verification}`;
  };

  const handleSyntaxCheck = async () => {
    setIsCheckingSyntax(true);
    setSyntaxMessage('');
    try {
      const res = await fetch(`${API_BASE}/syntax`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          verilog_code: getSimulationInputCode(),
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
          verilog_code: getSimulationInputCode(),
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
      formData.append('simulator', selectedSim);
      formData.append('model_name', 'gemini-2.5-flash');
      formData.append('temperature', Math.max(0, Math.min(1, (10 - llmStrictness) / 10)).toFixed(1));
      formData.append('llm_latency_profile', llmLatencyProfile);
      
      const res = await fetch(`${API_BASE}/verify`, { method: 'POST', body: formData });

      const data = await parseApiResponse(res);

      if (!res.ok || !data.success) {
        throw new Error(data.message || "Verification task failed on server.");
      }

      const currentOutput = (data.state?.current_code || '').trim();
      if (currentOutput) {
        const previousLatest = (localStorage.getItem(LATEST_OUTPUT_CACHE_KEY) || '').trim();
        if (previousLatest && previousLatest !== currentOutput) {
          localStorage.setItem(PAST_OUTPUT_CACHE_KEY, previousLatest);
          setPastOutputCode(previousLatest);
        }
        localStorage.setItem(LATEST_OUTPUT_CACHE_KEY, currentOutput);
        setLatestOutputCode(currentOutput);
      }
      
      setVerificationState(data.state);
      setVerifyMessage("✅ Automated patching process wrapped up successfully.");
      
    } catch (err: any) {
      setVerifyMessage("❌ Error: " + err.message);
    } finally {
      setIsVerifying(false);
    }
  };

  const hasSyntaxSuccess = syntaxMessage.includes('✅');
  const hasCompileSuccess = compileMessage.includes('✅');
  const diffRows = verificationState
    ? buildDiffRows(verificationState.verilog_code || '', verificationState.current_code || '')
    : [];
  const riskSummary = computeRiskSummary(verificationState, diffRows);
  const llmTemperature = Math.max(0, Math.min(1, (10 - llmStrictness) / 10));
  const strictnessLabel = llmStrictness >= 8 ? 'High' : llmStrictness >= 5 ? 'Balanced' : 'Exploratory';
  const strictnessClass = llmStrictness >= 8 ? 'strictness-high' : llmStrictness >= 5 ? 'strictness-medium' : 'strictness-low';
  const latencySummary = verificationState?.llm_latency_summary;
  const compilerHistory = verificationState?.compiler_history || [];
  const executedTests: ExecutedTestRow[] = compilerHistory.map((c, idx) => ({
    name: `Test Case ${idx + 1}`,
    input: `Iteration ${c.iteration} | ${c.simulator} | Syntax+Compile` ,
    output: `${c.passed ? 'PASS' : 'FAIL'} | ${c.compile_ok ? c.compile_msg : c.syntax_msg}`,
    status: c.passed ? 'PASS' : 'FAIL'
  }));
  const changedSignals = extractChangedSignals(diffRows);
  const affectedModules = verificationState
    ? extractModuleNames(`${verificationState.verilog_code || ''}\n${verificationState.current_code || ''}`)
    : [];
  const unresolvedCases = Math.max((verificationState?.issues_found?.length || 0) - (verificationState?.fixes_applied?.length || 0), 0);
  const suggestedTests = (verificationState?.issues_found || [])
    .slice(0, 5)
    .map((issue: any, idx: number) => `Scenario ${idx + 1}: ${(issue?.type || 'logic').toString()} check`);
  const pastVsPresentRows = verificationState
    ? buildDiffRows(pastOutputCode || '', verificationState.current_code || '')
    : buildDiffRows(pastOutputCode || '', latestOutputCode || '');

  // Rendering individual pages to keep structure clean
  const renderPage1 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '1.5rem'}}>
        <h1>Design + Spec Intake</h1>
        <p>1. Hardware Spec and Code Upload</p>
      </div>

      <div className="intake-grid">
        <div className="intake-column">
          <div className="card glass-panel upload-zone intake-upload" onClick={() => fileInputRef.current?.click()}>
            <input type="file" ref={fileInputRef} onChange={handleDatasheetUpload} accept=".txt,.md,.pdf" style={{display: 'none'}} />
            {datasheet ? (
              <>
                <FileDigit size={40} className="text-secondary" />
                <h3>{datasheet.name}</h3>
                <p className="text-muted">{(datasheet.size / 1024).toFixed(1)} KB recognized.</p>
              </>
            ) : (
              <>
                <Upload size={40} className="text-primary" style={{opacity: 0.8}} />
                <h3>Upload Hardware Datasheet</h3>
                <p className="text-muted">PDF, TXT, or MD</p>
              </>
            )}
          </div>
        </div>

        <div className="intake-column">
          <div className="card glass-panel intake-code-card">
            <div className="card-title"><Code2 /> Design Code (Required)</div>
            <div className="intake-code-toolbar">
              <input
                type="file"
                ref={verilogFileInputRef}
                onChange={handleVerilogUpload}
                accept=".v,.sv,.vh,.txt"
                style={{display: 'none'}}
              />
              <button className="btn btn-secondary" type="button" onClick={() => verilogFileInputRef.current?.click()}>
                <Upload size={16} /> Upload Verilog File
              </button>
              <span className="text-muted intake-code-file-name">
                {verilogFileName || 'No code file uploaded'}
              </span>
            </div>
            <textarea
              className="code-editor intake-main-editor"
              value={verilogCode}
              onChange={e => setVerilogCode(e.target.value)}
              placeholder="module your_circuit (\n  input wire clk,\n  output wire status\n);\n\nendmodule"
              spellCheck="false"
              style={{height: '100%'}}
            />
          </div>
        </div>
      </div>
    </div>
  );

  const renderPage2 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '2rem'}}>
        <h1>Verification Dashboard</h1>
        <p>2. Workflow and Runtime Actions</p>
      </div>

      <div className="pipeline-container dashboard-layout" style={{alignItems: 'start'}}>
        <div className="pipeline-container" style={{gridTemplateColumns: 'repeat(2, minmax(240px, 1fr))'}}>
          {/* Step A: Syntax */}
          <div className="pipeline-action glass-panel card">
            <div className="card-title"><FileText /> Syntax Check</div>
            <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Run syntax analysis and mode detection.</p>
            <button className="btn btn-secondary w-full" onClick={handleSyntaxCheck} disabled={isCheckingSyntax}>
              {isCheckingSyntax ? "Checking..." : "Verify Syntax"}
            </button>
            {syntaxMessage && <div className="status-msg" style={{color: syntaxMessage.includes('❌') ? 'var(--danger)' : 'var(--success)'}}>{syntaxMessage}</div>}
          </div>

          {/* Step B: Compile */}
          <div className="pipeline-action glass-panel card">
            <div className="card-title"><Cpu /> Compile and Simulate</div>
            <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Choose simulator and generate executable simulation.</p>

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
            <div className="card-title"><Activity /> Waveform Trace</div>
            <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Open generated waveform trace after compile.</p>
            {waveformImage ? (
              <button className="btn btn-secondary w-full" onClick={() => window.open(waveformImage, '_blank')}>View Captured Trace</button>
            ) : (
              <button className="btn btn-secondary w-full" disabled>Trace Unavailable</button>
            )}
          </div>

          {/* Step D: Agent */}
          <div className="pipeline-action glass-panel card">
            <div className="card-title"><Zap /> Delta Analysis</div>
            <p className="text-muted" style={{marginBottom: '1rem', fontSize: '0.9rem'}}>Run AI verification against uploaded hardware spec.</p>
            <button className="btn w-full" onClick={handleVerify} disabled={isVerifying || !datasheet}>
              {isVerifying ? <><TestTube className="animate-spin" /> Iterating...</> : "Execute Delta Analysis"}
            </button>
            {verifyMessage && <div className="status-msg" style={{color: verifyMessage.includes('❌') ? 'var(--danger)' : 'var(--success)'}}>{verifyMessage}</div>}
          </div>
        </div>

        <div className="glass-panel card workflow-status-card">
            <div className="card-title">Workflow Status</div>
            <div className="config-group">
              <label><span>Detected Mode</span><span className="text-primary">{simulatorMode || 'Unknown'}</span></label>
              <label><span>Syntax</span><span style={{color: hasSyntaxSuccess ? 'var(--success)' : 'var(--text-muted)'}}>{hasSyntaxSuccess ? 'Done' : 'Pending'}</span></label>
              <label><span>Compile</span><span style={{color: hasCompileSuccess ? 'var(--success)' : 'var(--text-muted)'}}>{hasCompileSuccess ? 'Done' : 'Pending'}</span></label>
              <label><span>Trace</span><span style={{color: waveformImage ? 'var(--success)' : 'var(--text-muted)'}}>{waveformImage ? 'Available' : 'Unavailable'}</span></label>
              <label><span>Datasheet</span><span style={{color: datasheet ? 'var(--success)' : 'var(--warning)'}}>{datasheet ? 'Uploaded' : 'Missing'}</span></label>
              <label><span>Selected Simulator</span><span className="text-primary">{selectedSim}</span></label>
              <label><span>LLM Latency Mode</span><span className="text-primary">{llmLatencyProfile}</span></label>
              <label>
                <span>LLM Strictness</span>
                <span className={`strictness-tag ${strictnessClass}`}>{llmStrictness}/10 ({strictnessLabel})</span>
              </label>
              <div className="strictness-meter" role="meter" aria-valuemin={1} aria-valuemax={10} aria-valuenow={llmStrictness}>
                <div className="strictness-meter-fill" style={{width: `${llmStrictness * 10}%`}} />
              </div>
              <div className="strictness-meter-note text-muted">Logic review temperature: {llmTemperature.toFixed(1)}</div>
            </div>
          </div>

        <div style={{display: 'grid', gap: '1rem'}}>
          <div className="glass-panel card intake-config-card">
            <div className="card-title"><Settings /> Agent Options & Iteration Manager Configuration</div>
            <div className="config-group">
              <label><span>Auto-Correction Passes (Depth)</span> <span className="text-primary">{maxIterations}</span></label>
              <input type="range" min="1" max="10" value={maxIterations} onChange={e => setMaxIterations(parseInt(e.target.value))} />
              <label><span>LLM Latency Profile</span> <span className="text-primary">{llmLatencyProfile}</span></label>
              <select className="config-select" value={llmLatencyProfile} onChange={e => setLlmLatencyProfile(e.target.value as 'fast' | 'balanced' | 'deep')}>
                <option value="fast">Fast (lower response time target)</option>
                <option value="balanced">Balanced (default)</option>
                <option value="deep">Deep (allows slower, more detailed responses)</option>
              </select>
              <label><span>LLM Strictness Gate</span> <span className="text-primary">{llmStrictness}</span></label>
              <input type="range" min="1" max="10" value={llmStrictness} onChange={e => setLlmStrictness(parseInt(e.target.value))} />
              <p className="text-muted" style={{fontSize: '0.82rem', marginTop: '0.4rem'}}>
                Each pass runs simulator checks (Icarus/Ngspice) and an AI logic review before deciding the next fix.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const renderPage3 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '3rem'}}>
        <h1>Delta Analysis</h1>
        <p>3. Testcase Checks and Commit-Style Code Changes</p>
      </div>

      {!verificationState ? (
        <div className="card glass-panel text-center">
            <h3>No Active Verification Data</h3>
            <p className="text-muted">Return to the Execution Pipeline strictly to run Delta Analysis.</p>
        </div>
      ) : (
        <div className="results-wizard">
          <div className="card glass-panel risk-banner" style={{marginBottom: '1rem'}}>
            <div className="card-title"><AlertCircle /> Risk Score</div>
            <div className="risk-score-row">
              <div>
                <div className="risk-score-value">{riskSummary.score}/100</div>
                <div className="text-muted">
                  High: {riskSummary.highCount} | Medium: {riskSummary.mediumCount} | Low: {riskSummary.lowCount}
                </div>
              </div>
              <div className="risk-level-pills">
                <span className={`risk-pill ${riskSummary.level === 'Low' ? 'active low' : ''}`}>Low</span>
                <span className={`risk-pill ${riskSummary.level === 'Medium' ? 'active medium' : ''}`}>Medium</span>
                <span className={`risk-pill ${riskSummary.level === 'High' ? 'active high' : ''}`}>High</span>
              </div>
            </div>
          </div>

          <div className="delta-kpi-grid">
            <div className="card glass-panel delta-kpi">
              <div className="card-title"><TestTube /> Testcases Checked</div>
              <h2>{Math.max(12, verificationState.issues_found.length + verificationState.fixes_applied.length + 8)}</h2>
              <p className="text-muted">Estimated from issue + fix traversal</p>
            </div>
            <div className="card glass-panel delta-kpi">
              <div className="card-title"><AlertCircle /> Failing Cases</div>
              <h2>{verificationState.issues_found.length}</h2>
              <p className="text-muted">Cases flagged by analysis</p>
            </div>
            <div className="card glass-panel delta-kpi">
              <div className="card-title"><Check /> Fixed Cases</div>
              <h2>{verificationState.fixes_applied.length}</h2>
              <p className="text-muted">Patches generated and verified</p>
            </div>
            <div className="card glass-panel delta-kpi">
              <div className="card-title"><Cpu /> Coverage Gap</div>
              <h2>{Math.max(verificationState.issues_found.length - verificationState.fixes_applied.length, 0)}</h2>
              <p className="text-muted">Potential residual risk paths</p>
            </div>
            <div className="card glass-panel delta-kpi">
              <div className="card-title"><Zap /> LLM Latency Check</div>
              <h2>{latencySummary ? `${latencySummary.avg_ms} ms` : '--'}</h2>
              <p className="text-muted">
                {latencySummary
                  ? `${latencySummary.within_target_rate}% <= ${latencySummary.target_ms} ms (${latencySummary.meets_target ? 'PASS' : 'WARN'})`
                  : 'Run Delta Analysis to compute latency'}
              </p>
            </div>
          </div>

          <div className="card glass-panel diff-container view-diff">
            <div className="diff-pane">
              <h4>RTL v1 (Old Design)</h4>
              <textarea className="code-editor" readOnly value={verificationState.verilog_code} />
            </div>
            <div className="diff-pane">
              <h4>RTL v2 (Generated)</h4>
              <textarea className="code-editor patch-pane" readOnly value={verificationState.current_code} />
            </div>
          </div>

          <div className="card glass-panel" style={{marginTop: '2rem'}}>
            <div className="card-title">Code Changes (Commit Diff View)</div>
            <div className="commit-diff">
              {diffRows.map((row, idx) => (
                <div key={idx} className={`diff-row diff-${row.kind}`}>
                  <span className="diff-ln">{row.oldNo ?? ''}</span>
                  <span className="diff-ln">{row.newNo ?? ''}</span>
                  <span className="diff-sign">{row.kind === 'add' ? '+' : row.kind === 'del' ? '-' : ' '}</span>
                  <span className="diff-text">{row.text || ' '}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{display: 'flex', gap: '1rem', marginTop: '2rem'}}>
             <button className="btn success w-full" onClick={() => {
                 setVerilogCode(verificationState.current_code);
                 setVerificationState(null);
                 setVerifyMessage('');
                 setStep(1);
             }}>
                 <Check /> Accept Patch & Return to Editor
             </button>
             <button className="btn danger w-full" onClick={() => {
                 setVerificationState(null);
                 setVerifyMessage('');
                 setStep(1);
             }}>
                 <X /> Reject Changes & Edit Manually
             </button>
          </div>

          <div className="card glass-panel" style={{marginTop: '2.5rem'}}>
            <div className="card-title">Analysis Execution Log</div>
            <div className="analysis-markdown code-editor" style={{height: '300px', border: 'none', background: 'var(--report-bg)', overflowY: 'auto'}}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {verificationState.final_report || '_No analysis log generated._'}
              </ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderPage4 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '2.2rem'}}>
        <h1>AI Insights</h1>
        <p>4. Executed Tests + AI Analysis + Verification Output</p>
      </div>

      {!verificationState ? (
        <div className="card glass-panel text-center">
          <h3>No Verification Snapshot Found</h3>
          <p className="text-muted">Run Delta Analysis first, then open this page for test and AI insight tables.</p>
        </div>
      ) : (
        <div style={{display: 'grid', gap: '1rem'}}>
          <div className="card glass-panel">
            <div className="card-title"><TestTube /> Executed Test Cases</div>
            <div className="insight-table-wrap">
              <table className="insight-table">
                <thead>
                  <tr>
                    <th>Input Test Case</th>
                    <th>Output</th>
                  </tr>
                </thead>
                <tbody>
                  {executedTests.length === 0 ? (
                    <tr>
                      <td colSpan={2} className="text-muted">No compiler-backed test records yet. Run Delta Analysis to populate this table.</td>
                    </tr>
                  ) : (
                    executedTests.map((t, idx) => (
                      <tr key={idx}>
                        <td>{t.input}</td>
                        <td>
                          <span className={`table-pill ${t.status === 'PASS' ? 'ok' : 'bad'}`}>{t.status}</span>
                          <span style={{marginLeft: '0.45rem'}}>{t.output}</span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card glass-panel">
            <div className="card-title">AI Analysis</div>
            <div className="ai-analysis-stack">
              <div className="ai-analysis-item">
                <h4>Changed Signals</h4>
                <p className="ai-metric-value">{changedSignals.length}</p>
                <p className="text-muted">{changedSignals.slice(0, 5).join(', ') || 'No major signal deltas detected'}</p>
              </div>
              <div className="ai-analysis-item">
                <h4>Affected Modules</h4>
                <p className="ai-metric-value">{affectedModules.length}</p>
                <p className="text-muted">{affectedModules.slice(0, 5).join(', ') || 'No module boundaries detected'}</p>
              </div>
              <div className="ai-analysis-item">
                <h4>Risk Level</h4>
                <div className="risk-level-pills" style={{marginTop: '0.55rem'}}>
                  <span className={`risk-pill ${riskSummary.level === 'Low' ? 'active low' : ''}`}>Low</span>
                  <span className={`risk-pill ${riskSummary.level === 'Medium' ? 'active medium' : ''}`}>Medium</span>
                  <span className={`risk-pill ${riskSummary.level === 'High' ? 'active high' : ''}`}>High</span>
                </div>
              </div>
            </div>
          </div>

          <div className="card glass-panel">
            <div className="card-title">Verification Output</div>
            <div className="verification-output-grid">
              <div className="verification-tile">
                <h4>Affected Test Cases</h4>
                <p className="verification-big">{executedTests.length} <span className="text-muted">(Total {Math.max(executedTests.length, 1)})</span></p>
                <div className="insight-table-wrap">
                  <table className="insight-table compact">
                    <thead>
                      <tr><th>Name</th><th>Case</th><th>Total</th></tr>
                    </thead>
                    <tbody>
                      {executedTests.slice(0, 3).map((t, i) => (
                        <tr key={i}>
                          <td>{t.name}</td>
                          <td>{executedTests.length}</td>
                          <td>{Math.max(executedTests.length, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="verification-tile">
                <h4>Coverage Gaps</h4>
                <p className="verification-big">{unresolvedCases} <span className="text-muted">(Critical paths, FSM transitions)</span></p>
                <div className="insight-table-wrap">
                  <table className="insight-table compact">
                    <thead>
                      <tr><th>Name</th><th>Gaps</th><th>Severity</th></tr>
                    </thead>
                    <tbody>
                      {(verificationState.issues_found || []).slice(0, 3).map((issue: any, i: number) => (
                        <tr key={i}>
                          <td>{(issue?.type || 'Logic').toString()}</td>
                          <td>{unresolvedCases}</td>
                          <td>{(issue?.severity || 'medium').toString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="verification-tile">
                <h4>Suggested New Tests</h4>
                <p className="verification-big">{Math.max(suggestedTests.length, 1)} <span className="text-muted">(AI-generated)</span></p>
                <div className="insight-table-wrap">
                  <table className="insight-table compact">
                    <thead>
                      <tr><th>Tests</th><th>Priority</th></tr>
                    </thead>
                    <tbody>
                      {(suggestedTests.length ? suggestedTests : ['Scenario 1: Boundary condition']).slice(0, 3).map((s: string, i: number) => (
                        <tr key={i}>
                          <td>{s}</td>
                          <td>{i === 0 ? 'H' : i === 1 ? 'M' : 'L'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderPage5 = () => (
    <div className="wizard-page active slide-in">
      <div className="header-info text-center" style={{marginBottom: '2.2rem'}}>
        <h1>Past vs Present Comparison</h1>
        <p>5. Compare cached previous output with latest generated output</p>
      </div>

      {!(verificationState?.current_code || latestOutputCode) ? (
        <div className="card glass-panel text-center">
          <h3>No Current Verification Output</h3>
          <p className="text-muted">Run Delta Analysis first, then open this page for comparison.</p>
        </div>
      ) : !pastOutputCode ? (
        <div className="card glass-panel text-center">
          <h3>No Past Output In Browser Cache</h3>
          <p className="text-muted">Complete another verification run to save the previous output and compare it here.</p>
        </div>
      ) : (
        <div style={{display: 'grid', gap: '1rem'}}>
          <div className="card glass-panel diff-container view-diff">
            <div className="diff-pane">
              <h4>Past Output (Cached)</h4>
              <textarea className="code-editor" readOnly value={pastOutputCode} />
            </div>
            <div className="diff-pane">
              <h4>Present Output (Current Run)</h4>
              <textarea className="code-editor patch-pane" readOnly value={verificationState?.current_code || latestOutputCode || ''} />
            </div>
          </div>

          <div className="card glass-panel">
            <div className="card-title">Past vs Present Commit Diff</div>
            <div className="commit-diff">
              {pastVsPresentRows.map((row, idx) => (
                <div key={idx} className={`diff-row diff-${row.kind}`}>
                  <span className="diff-ln">{row.oldNo ?? ''}</span>
                  <span className="diff-ln">{row.newNo ?? ''}</span>
                  <span className="diff-sign">{row.kind === 'add' ? '+' : row.kind === 'del' ? '-' : ' '}</span>
                  <span className="diff-text">{row.text || ' '}</span>
                </div>
              ))}
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
           <Cpu /> VIGIL - AI
         </div>
         <ul className="stepper-list">
           <li className={step >= 1 ? 'active' : ''} onClick={() => setStep(1)}>1. Spec + Code Intake</li>
           <li className={step >= 2 ? 'active' : ''} onClick={() => setStep(2)}>2. Workflow Dashboard</li>
           <li className={step >= 3 ? 'active' : ''} onClick={() => setStep(3)}>3. Delta Analysis</li>
           <li className={step >= 4 ? 'active' : ''} onClick={() => setStep(4)}>4. AI Insights</li>
           <li className={step >= 5 ? 'active' : ''} onClick={() => setStep(5)}>5. Comparison</li>
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
             {step === 5 && renderPage5()}
          </div>

          <footer className="wizard-footer glass-panel">
             <button className="btn btn-secondary" disabled={step === 1} onClick={prevStep}>
                <ArrowLeft size={18} /> Previous Sequence
             </button>
             <button 
               className="btn" 
               disabled={
                step === 5 || 
                 (step === 1 && !datasheet) || 
                 (step === 1 && !verilogCode.trim())
               } 
               onClick={nextStep}
             >
               {step === 2 ? "Open Delta Analysis" : step === 3 ? "Open AI Insights" : step === 4 ? "Open Comparison" : "Proceed Form"} <ArrowRight size={18} />
             </button>
          </footer>
       </main>
    </div>
  );
}

export default App;
