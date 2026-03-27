"""
Waveform Generator for Verilog Code
Generates VCD files and waveform images from Verilog testbenches
"""

import subprocess
import tempfile
import os
import shutil
import re
from pathlib import Path
from typing import Optional, Tuple
import matplotlib

# Use a headless backend so plotting works inside FastAPI worker threads.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from vcdvcd import VCDVCD
except ImportError:
    VCDVCD = None


class WaveformGenerator:
    """Generate waveforms from Verilog code or SPICE netlists"""
    
    def __init__(self, simulator="xyce", xyce_path=None):
        self.temp_dir = tempfile.mkdtemp()
        self.simulator = simulator  # "iverilog", "ngspice", or "xyce"
        self.xyce_path = xyce_path or "Xyce"  # Use custom path or default
        self.sim_file = os.path.join(self.temp_dir, "sim")
        self.verilog_file = os.path.join(self.temp_dir, "test.v")
        self.tb_file = os.path.join(self.temp_dir, "auto_tb.v")
        self.spice_file = os.path.join(self.temp_dir, "circuit.cir")

    def _extract_code(self, code: str) -> str:
        """Extract code body from markdown code fences if present."""
        if "```verilog" in code:
            return code.split("```verilog", 1)[1].split("```", 1)[0].strip()
        if "```" in code:
            return code.split("```", 1)[1].split("```", 1)[0].strip()
        return code.strip()

    def _is_verilog_module(self, code: str) -> bool:
        lower = code.lower()
        return "module" in lower and "endmodule" in lower

    def _is_verilog_ams(self, code: str) -> bool:
        lower = code.lower()
        return (
            "`include \"disciplines.vams\"" in lower
            or "analog begin" in lower
            or "electrical " in lower
            or "<+" in code
        )

    def _run_verilog_syntax_check(self) -> Tuple[bool, str]:
        """Run syntax check using installed Verilog toolchain."""
        iverilog_bin = self._resolve_executable("iverilog")
        if iverilog_bin:
            result = subprocess.run(
                [iverilog_bin, "-g2012", "-Wall", "-t", "null", "test.v"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            output = (result.stderr or "").strip() or (result.stdout or "").strip()
            if result.returncode != 0:
                return False, f"Icarus Verilog syntax error:\n{output}"
            return True, "Icarus Verilog syntax check passed"

        verilator_bin = self._resolve_executable("verilator")
        if verilator_bin:
            result = subprocess.run(
                [verilator_bin, "--lint-only", "--Wall", "test.v"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            output = (result.stderr or "").strip() or (result.stdout or "").strip()
            if result.returncode != 0:
                return False, f"Verilator lint/syntax error:\n{output}"
            return True, "Verilator lint/syntax check passed"

        return False, (
            "No Verilog compiler found. Install one of: "
            "iverilog (recommended) or verilator."
        )

    def _resolve_executable(self, cmd: str) -> Optional[str]:
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

    def _generate_auto_testbench(self, verilog_code: str) -> Tuple[bool, str, str]:
        """Generate a minimal digital testbench when design code has no dump statements."""
        module_match = re.search(r"module\s+(\w+)\s*\((.*?)\)\s*;", verilog_code, flags=re.IGNORECASE | re.DOTALL)
        if not module_match:
            return False, "", "Unable to auto-generate testbench: no valid module header found"

        module_name = module_match.group(1)
        ports_raw = module_match.group(2)

        # Strip inline comments before token parsing.
        ports_raw_no_comments = "\n".join(
            line.split("//", 1)[0] for line in ports_raw.splitlines()
        )
        port_entries = [p.strip() for p in ports_raw_no_comments.split(",") if p.strip()]

        parsed_ports = []
        ansi_port_re = re.compile(
            r"^(?:(input|output|inout)\s+)?(?:(?:reg|wire|logic)\s+)?(\[[^\]]+\]\s*)?(\w+)$",
            flags=re.IGNORECASE,
        )
        for entry in port_entries:
            m = ansi_port_re.match(entry)
            if m:
                direction = (m.group(1) or "input").lower()
                width = (m.group(2) or "").strip()
                name = m.group(3)
                parsed_ports.append((name, direction, width))
            else:
                # Fallback: best-effort token extraction.
                tokens = entry.split()
                if not tokens:
                    continue
                name = tokens[-1]
                parsed_ports.append((name, "input", ""))

        body_start = module_match.end()
        endmodule_match = re.search(r"\bendmodule\b", verilog_code[body_start:], flags=re.IGNORECASE)
        module_body = verilog_code[body_start:body_start + endmodule_match.start()] if endmodule_match else verilog_code[body_start:]

        port_info = {}
        decl_re = re.compile(r"\b(input|output|inout)\b\s*(?:reg|wire)?\s*(\[[^\]]+\])?\s*([^;]+);", flags=re.IGNORECASE)
        for m in decl_re.finditer(module_body):
            direction = m.group(1).lower()
            width = (m.group(2) or "").strip()
            names_part = m.group(3)
            for raw_name in names_part.split(","):
                name = raw_name.strip()
                if not name:
                    continue
                name = name.split("=")[0].strip()
                port_info[name] = (direction, width)

        # For non-ANSI declarations, refine any unknown/default ports from body declarations.
        refined_ports = []
        for name, direction, width in parsed_ports:
            if name in port_info:
                d, w = port_info[name]
                refined_ports.append((name, d, w or width))
            else:
                refined_ports.append((name, direction, width))

        signal_decls = []
        inst_conn = []
        clock_inputs = []
        reset_inputs = []
        toggle_inputs = []

        for p, direction, width in refined_ports:

            if direction == "output":
                signal_decls.append(f"wire {width} {p};".replace("  ", " ").strip())
            elif direction == "inout":
                signal_decls.append(f"wire {width} {p};".replace("  ", " ").strip())
            else:
                signal_decls.append(f"reg {width} {p};".replace("  ", " ").strip())
                if re.search(r"clk|clock", p, flags=re.IGNORECASE):
                    clock_inputs.append(p)
                elif re.search(r"rst|reset", p, flags=re.IGNORECASE):
                    reset_inputs.append(p)
                else:
                    toggle_inputs.append(p)

            inst_conn.append(f".{p}({p})")

        init_lines = ["  $dumpfile(\"waveform.vcd\");", "  $dumpvars(0, auto_tb);"]
        for name, direction, _ in refined_ports:
            if direction == "input":
                if name in reset_inputs:
                    init_lines.append(f"  {name} = 1'b1;")
                else:
                    init_lines.append(f"  {name} = 0;")

        init_lines.append("  #10;")
        for rst in reset_inputs:
            init_lines.append(f"  {rst} = 1'b0;")

        if toggle_inputs:
            init_lines.append("  repeat (20) begin")
            init_lines.append("    #10;")
            for sig in toggle_inputs:
                init_lines.append(f"    {sig} = ~{sig};")
            init_lines.append("  end")
            init_lines.append("  #20;")
        else:
            init_lines.append("  #200;")

        init_lines.append("  $finish;")

        clock_blocks = []
        for clk in clock_inputs:
            clock_blocks.append(f"always #5 {clk} = ~{clk};")

        tb = [
            "`timescale 1ns/1ps",
            "module auto_tb;",
            *signal_decls,
            "",
            f"{module_name} uut (",
            "  " + ",\n  ".join(inst_conn),
            ");",
            "",
            *clock_blocks,
            "",
            "initial begin",
            *init_lines,
            "end",
            "",
            "endmodule",
            "",
        ]

        return True, "\n".join(tb), module_name

    def _run_spice_syntax_check(self) -> Tuple[bool, str]:
        """Run SPICE parser/syntax check using selected analog simulator."""
        if self.simulator == "ngspice":
            ngspice_bin = self._resolve_executable("ngspice")
            if not ngspice_bin:
                return False, "Ngspice not found. Install ngspice to validate Verilog-AMS/SPICE syntax."

            result = subprocess.run(
                [ngspice_bin, "-b", "-o", "syntax.log", "circuit.cir"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            output = (result.stderr or "").strip() or (result.stdout or "").strip()
            if result.returncode != 0:
                return False, f"Ngspice syntax/netlist error:\n{output}"
            return True, "Ngspice syntax/netlist check passed"

        if self.simulator == "xyce":
            xyce_bin = self.xyce_path if (os.path.isabs(self.xyce_path) and os.path.exists(self.xyce_path)) else self._resolve_executable(self.xyce_path)
            if not xyce_bin:
                return False, "Xyce not found. Install Xyce (or set xyce_path) to validate Verilog-AMS/SPICE syntax."

            result = subprocess.run(
                [xyce_bin, "circuit.cir"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            output = (result.stderr or "").strip() or (result.stdout or "").strip()
            if result.returncode != 0:
                return False, f"Xyce syntax/netlist error:\n{output}"
            return True, "Xyce syntax/netlist check passed"

        return False, "SPICE syntax check requires simulator='ngspice' or simulator='xyce'."

    def _basic_verilog_ams_sanity_check(self, verilog_code: str) -> Tuple[bool, str]:
        """Catch obvious Verilog-AMS syntax issues before conversion."""
        lines = verilog_code.splitlines()
        cleaned_lines = []
        for line in lines:
            # Strip single-line comments for simple token checks.
            cleaned_lines.append(line.split("//", 1)[0])
        cleaned = "\n".join(cleaned_lines)

        module_count = len(re.findall(r"\bmodule\b", cleaned, flags=re.IGNORECASE))
        endmodule_count = len(re.findall(r"\bendmodule\b", cleaned, flags=re.IGNORECASE))
        if module_count == 0:
            return False, "Verilog-AMS syntax error: missing 'module' declaration"
        if module_count != endmodule_count:
            return False, (
                "Verilog-AMS syntax error: mismatched module/endmodule "
                f"({module_count} module, {endmodule_count} endmodule)"
            )

        begin_count = len(re.findall(r"\bbegin\b", cleaned, flags=re.IGNORECASE))
        end_count = len(re.findall(r"\bend\b", cleaned, flags=re.IGNORECASE))
        if begin_count != end_count:
            return False, (
                "Verilog-AMS syntax error: mismatched begin/end "
                f"({begin_count} begin, {end_count} end)"
            )

        pairs = [("(", ")"), ("[", "]"), ("{", "}")]
        for left, right in pairs:
            if cleaned.count(left) != cleaned.count(right):
                return False, (
                    "Verilog-AMS syntax error: unbalanced bracket pair "
                    f"'{left}{right}'"
                )

        for line_no, raw in enumerate(lines, start=1):
            code = raw.split("//", 1)[0].strip()
            if not code:
                continue

            if "<+" in code and not code.endswith(";"):
                return False, (
                    f"Verilog-AMS syntax error at line {line_no}: contribution statement "
                    "must end with ';'"
                )

            decl_keywords = ("parameter", "input", "output", "inout", "electrical", "real")
            if code.startswith(decl_keywords) and not code.endswith(";"):
                return False, (
                    f"Verilog-AMS syntax error at line {line_no}: declaration must end with ';'"
                )

        return True, "Verilog-AMS structural sanity check passed"
    
    def compile_verilog(self, verilog_code: str) -> Tuple[bool, str]:
        """
        Compile Verilog code or prepare SPICE netlist
        
        Args:
            verilog_code: Verilog code with testbench or SPICE netlist
            
        Returns:
            Tuple of (success, message)
        """
        if self.simulator in ["ngspice", "xyce"]:
            return self.prepare_spice(verilog_code)
        
        # Clean the verilog code - remove markdown if present
        if "```verilog" in verilog_code:
            verilog_code = verilog_code.split("```verilog")[1].split("```")[0].strip()
        elif "```" in verilog_code:
            verilog_code = verilog_code.split("```")[1].split("```")[0].strip()
        
        # Check if code has module
        if "module" not in verilog_code.lower():
            return False, "No Verilog module found in code"

        iverilog_bin = self._resolve_executable("iverilog")
        if not iverilog_bin:
            return False, "iverilog not found. Install from: http://bleyer.org/icarus/"
        
        # Save Verilog code to temp file
        try:
            with open(self.verilog_file, 'w', encoding='utf-8') as f:
                f.write(verilog_code)
        except Exception as e:
            return False, f"Failed to write file: {e}"
        
        try:
            compile_inputs = ["test.v"]
            auto_tb_used = False

            # If no waveform dump directives are present, auto-generate a simple TB.
            if "$dumpfile" not in verilog_code and "$dumpvars" not in verilog_code:
                tb_ok, tb_code, module_name = self._generate_auto_testbench(verilog_code)
                if not tb_ok:
                    return False, tb_code
                with open(self.tb_file, 'w', encoding='utf-8') as f:
                    f.write(tb_code)
                compile_inputs.append("auto_tb.v")
                auto_tb_used = True

            # Compile: iverilog -o sim test.v [auto_tb.v]
            result = subprocess.run(
                [iverilog_bin, "-g2012", "-o", "sim", *compile_inputs],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            
            if result.returncode != 0:
                return False, f"Compilation error: {result.stderr}"

            if auto_tb_used:
                return True, "Compilation successful (auto-generated testbench and VCD trace)"
            return True, "Compilation successful"
            
        except Exception as e:
            return False, f"Error: {str(e)}"
            
    def check_syntax(self, verilog_code: str) -> Tuple[bool, str]:
        """Perform syntax check without compiling output for Verilog"""
        verilog_code = self._extract_code(verilog_code)

        if not verilog_code:
            return False, "No code provided"

        if self._is_verilog_module(verilog_code):
            if self._is_verilog_ams(verilog_code):
                # Verilog-AMS is validated via SPICE-compatible simulator path.
                if self.simulator not in ["ngspice", "xyce"]:
                    if self._resolve_executable("ngspice"):
                        self.simulator = "ngspice"
                    elif self._resolve_executable("Xyce"):
                        self.simulator = "xyce"
                    else:
                        return False, (
                            "Detected Verilog-AMS. Install ngspice or Xyce for syntax/netlist validation. "
                            "Digital compilers (Icarus/Verilator) cannot parse Verilog-AMS."
                        )

                success, msg = self.prepare_spice(verilog_code)
                if not success:
                    return success, msg
                syntax_ok, syntax_msg = self._run_spice_syntax_check()
                if not syntax_ok:
                    return syntax_ok, syntax_msg
                return True, f"{msg}. {syntax_msg}"

            try:
                with open(self.verilog_file, 'w', encoding='utf-8') as f:
                    f.write(verilog_code)
            except Exception as e:
                return False, f"Failed to write file: {e}"
            return self._run_verilog_syntax_check()

        if self.simulator in ["ngspice", "xyce"]:
            success, msg = self.prepare_spice(verilog_code)
            if not success:
                return success, msg
            syntax_ok, syntax_msg = self._run_spice_syntax_check()
            if not syntax_ok:
                return syntax_ok, syntax_msg
            return True, f"{msg}. {syntax_msg}"
            
        try:
            with open(self.verilog_file, 'w', encoding='utf-8') as f:
                f.write(verilog_code)
        except Exception as e:
            return False, f"Failed to write file: {e}"
        return self._run_verilog_syntax_check()
    
    def prepare_spice(self, spice_code: str) -> Tuple[bool, str]:
        """
        Prepare SPICE netlist for Ngspice or Xyce
        
        Args:
            spice_code: SPICE netlist code or Verilog-AMS
            
        Returns:
            Tuple of (success, message)
        """
        # Check if it's Verilog-AMS and convert to SPICE
        if "module" in spice_code and "analog" in spice_code:
            sanity_ok, sanity_msg = self._basic_verilog_ams_sanity_check(spice_code)
            if not sanity_ok:
                return False, sanity_msg

            spice_code = self._convert_verilog_ams_to_spice(spice_code)
            if spice_code.startswith("ERROR:"):
                return False, spice_code
        
        # Clean markdown if present
        if "```" in spice_code:
            parts = spice_code.split("```")
            for part in parts:
                if part.strip() and not part.strip().startswith(('spice', 'cir')):
                    spice_code = part.strip()
                    break
        
        # Save SPICE netlist
        try:
            with open(self.spice_file, 'w', encoding='utf-8', newline='\n') as f:
                f.write(spice_code)
                # Ensure it has .end
                if ".end" not in spice_code.lower():
                    f.write("\n.END\n")
            
            # Verify file was created
            if not os.path.exists(self.spice_file):
                return False, "Failed to create netlist file"
            
            return True, f"{self.simulator.capitalize()} netlist prepared"
        except Exception as e:
            return False, f"Failed to write file: {e}"
    
    def _convert_verilog_ams_to_spice(self, verilog_code: str) -> str:
        """
        Convert Verilog-AMS to equivalent SPICE netlist
        This is a simplified converter for the modamp module
        """
        try:
            # Extract module name and ports
            if "modamp" not in verilog_code:
                return "ERROR: Only modamp module is supported for auto-conversion"
            
            # Create equivalent SPICE netlist
            spice = "* Auto-converted from Verilog-AMS modamp module\n"
            spice += "* Simplified behavioral op-amp model\n\n"
            
            # Simple op-amp subcircuit
            spice += ".SUBCKT modamp inp inn outp\n"
            spice += "* Input resistances\n"
            spice += "RIN1 inp 0 1MEG\n"
            spice += "RIN2 inn 0 1MEG\n"
            spice += "CIN inp inn 1p\n\n"
            
            spice += "* Differential amplifier with gain\n"
            spice += "EDIFF n1 0 inp inn 1e6\n"
            spice += "RPOLE1 n1 n2 1k\n"
            spice += "CPOLE1 n2 0 0.159u\n\n"
            
            spice += "* Output stage\n"
            spice += "EOUT n3 0 n2 0 1\n"
            spice += "ROUT n3 outp 75\n"
            spice += ".ENDS modamp\n\n"
            
            # Testbench
            spice += "* Testbench\n"
            spice += "VIN1 inp 0 SIN(0 0.01 1k)\n"
            spice += "VIN2 inn 0 DC 0\n"
            spice += "X1 inp inn outp modamp\n"
            spice += "RL outp 0 10k\n\n"
            
            spice += "* Analysis\n"
            spice += ".TRAN 1u 5m\n"
            spice += ".PRINT TRAN V(inp) V(inn) V(outp)\n"
            spice += ".END\n"
            
            return spice
            
        except Exception as e:
            return f"ERROR: Conversion failed: {str(e)}"
    
    def generate_waveform_from_sim(self) -> Tuple[Optional[str], Optional[str], str]:
        """
        Generate waveform from compiled sim file
        
        Returns:
            Tuple of (vcd_path, image_path, error_message)
        """
        if self.simulator == "ngspice":
            return self.run_ngspice_simulation()
        elif self.simulator == "xyce":
            return self.run_xyce_simulation()
        
        try:
            vvp_bin = self._resolve_executable("vvp")
            if not vvp_bin:
                return None, None, "vvp not found. Install iverilog from: http://bleyer.org/icarus/"

            # Simulate: vvp sim
            result = subprocess.run(
                [vvp_bin, "sim"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            
            if result.returncode != 0:
                return None, None, f"Simulation error: {result.stderr}"
            
            # Find VCD file in temp directory
            vcd_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.vcd')]
            if not vcd_files:
                return None, None, f"No VCD file generated. Ensure code has $dumpfile() and $dumpvars()"
            
            vcd_path = os.path.join(self.temp_dir, vcd_files[0])
            
            # Generate waveform image
            if not VCDVCD:
                return vcd_path, None, "vcdvcd library not installed. Run: pip install vcdvcd"
            
            image_path = self._generate_image(vcd_path)
            if not image_path:
                return vcd_path, None, "Failed to generate waveform image"
            
            return vcd_path, image_path, "Success"
            
        except Exception as e:
            return None, None, f"Error: {str(e)}"
    
    def run_xyce_simulation(self) -> Tuple[Optional[str], Optional[str], str]:
        """
        Run Xyce simulation and generate waveform
        
        Returns:
            Tuple of (data_path, image_path, error_message)
        """
        try:
            # Run: Xyce circuit.cir
            result = subprocess.run(
                [self.xyce_path, "circuit.cir"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            
            if result.returncode != 0:
                error_msg = result.stderr if result.stderr else result.stdout
                return None, None, f"Xyce error: {error_msg}\n\nNote: Xyce requires SPICE netlist format, not Verilog-AMS. Your file needs a testbench with voltage sources, .TRAN, and .PRINT statements."
            
            # Xyce generates .prn files by default
            prn_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.prn')]
            if not prn_files:
                return None, None, "No output file generated. Add .PRINT statement to netlist"
            
            # Generate waveform from .prn output
            image_path = self._generate_xyce_plot(prn_files[0])
            if not image_path:
                return None, None, "Failed to generate waveform from Xyce output"
            
            return prn_files[0], image_path, "Success"
            
        except FileNotFoundError:
            return None, None, "Xyce not installed. Download from: https://xyce.sandia.gov/downloads/ and add to PATH"
        except Exception as e:
            return None, None, f"Error: {str(e)}"
    
    def _generate_xyce_plot(self, prn_file: str) -> Optional[str]:
        """Generate waveform plot from Xyce .prn output"""
        try:
            prn_path = os.path.join(self.temp_dir, prn_file)
            
            # Parse Xyce .prn file
            data = {}
            with open(prn_path, 'r') as f:
                lines = f.readlines()
                # Skip header lines
                header_idx = 0
                for i, line in enumerate(lines):
                    if line.strip().startswith('TIME') or line.strip().startswith('Index'):
                        header_idx = i
                        headers = line.strip().split()
                        for h in headers:
                            data[h] = []
                        break
                
                # Parse data
                for line in lines[header_idx+1:]:
                    if line.strip():
                        values = line.strip().split()
                        for i, h in enumerate(headers):
                            if i < len(values):
                                try:
                                    data[h].append(float(values[i]))
                                except:
                                    pass
            
            # Plot
            plt.figure(figsize=(20, 6))
            
            time_key = 'TIME' if 'TIME' in data else 'Index'
            for key in data:
                if key != time_key and len(data[key]) > 0:
                    plt.plot(data[time_key], data[key], label=key)
            
            plt.xlabel("Time (s)")
            plt.ylabel("Voltage/Current")
            plt.title("Xyce Waveform")
            plt.legend()
            plt.grid(True)
            plt.tight_layout()
            
            image_path = os.path.join(self.temp_dir, "waveform.png")
            plt.savefig(image_path)
            plt.close()
            
            return image_path
            
        except Exception as e:
            print(f"Error generating Xyce plot: {e}")
            return None
    
    def run_ngspice_simulation(self) -> Tuple[Optional[str], Optional[str], str]:
        """
        Run Ngspice simulation and generate waveform
        
        Returns:
            Tuple of (data_path, image_path, error_message)
        """
        try:
            ngspice_bin = self._resolve_executable("ngspice")
            if not ngspice_bin:
                return None, None, "ngspice not found. Install from: http://ngspice.sourceforge.net/"

            # Run: ngspice -b circuit.cir -o output.log
            result = subprocess.run(
                [ngspice_bin, "-b", "circuit.cir", "-o", "output.log"],
                capture_output=True,
                text=True,
                cwd=self.temp_dir,
                shell=False
            )
            
            if result.returncode != 0:
                return None, None, f"Ngspice error: {result.stderr}"
            
            # Generate waveform from output
            image_path = self._generate_ngspice_plot()
            if not image_path:
                return None, None, "Failed to generate waveform from Ngspice output"
            
            return None, image_path, "Success"
            
        except Exception as e:
            return None, None, f"Error: {str(e)}"
    

    
    def _generate_image(self, vcd_path: str) -> Optional[str]:
        """Generate waveform image from VCD file"""
        if not VCDVCD:
            return None
        
        try:
            vcd = VCDVCD(vcd_path)
            signals = vcd.signals
            
            if not signals:
                return None
            
            def decode_vcd_value(raw: str) -> Optional[int]:
                val = str(raw).strip()
                if not val:
                    return None

                if val.startswith(("b", "B")):
                    bits = val[1:]
                else:
                    bits = val

                if all(ch in "01xXzZ" for ch in bits):
                    if any(ch in "xXzZ" for ch in bits):
                        return None
                    return int(bits, 2)

                try:
                    return int(val)
                except ValueError:
                    return None

            plt.figure(figsize=(22, 8))
            lane_height = 1.0
            lane_gap = 0.6
            y_ticks = []
            y_labels = []

            for idx, signal in enumerate(signals):
                tv = vcd[signal].tv
                if not tv:
                    continue

                times = []
                values = []
                last_known = 0

                for t, raw in tv:
                    decoded = decode_vcd_value(raw)
                    if decoded is None:
                        decoded = last_known
                    else:
                        last_known = decoded
                    times.append(t)
                    values.append(decoded)

                if not values:
                    continue

                v_min = min(values)
                v_max = max(values)
                span = v_max - v_min
                if span > 0:
                    norm_values = [(v - v_min) / span for v in values]
                    label = f"{signal} [{v_min}..{v_max}]"
                else:
                    norm_values = [0.0 for _ in values]
                    label = f"{signal} [{v_min}]"

                lane_base = idx * (lane_height + lane_gap)
                lane_values = [lane_base + v for v in norm_values]
                plt.step(times, lane_values, where="post", linewidth=1.6, label=label)

                y_ticks.append(lane_base + 0.5)
                y_labels.append(signal)

            plt.xlabel("Time")
            plt.ylabel("Signals")
            plt.title("Digital Waveform")
            if y_ticks:
                plt.yticks(y_ticks, y_labels)
            plt.legend(loc="upper right", fontsize=8)
            plt.grid(True, axis="x", alpha=0.4)
            plt.tight_layout()
            
            image_path = os.path.join(self.temp_dir, "waveform.png")
            plt.savefig(image_path)
            plt.close()
            
            return image_path
            
        except Exception as e:
            print(f"Error generating image: {e}")
            return None
    
    def _generate_ngspice_plot(self) -> Optional[str]:
        """Generate waveform plot from Ngspice output"""
        try:
            output_file = os.path.join(self.temp_dir, "output.log")
            if not os.path.exists(output_file):
                return None

            headers = None
            times = []
            series = {}

            with open(output_file, 'r', encoding='utf-8', errors='ignore') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue

                    if line.startswith("Index"):
                        parts = line.split()
                        if len(parts) >= 3 and parts[1].lower() == "time":
                            headers = parts
                            for h in headers[2:]:
                                series.setdefault(h, [])
                        continue

                    if headers is None:
                        continue

                    if line.startswith("-"):
                        continue

                    parts = line.split()
                    if len(parts) < len(headers):
                        continue

                    # Ngspice rows are: Index time v(...) v(...) ...
                    try:
                        int(parts[0])
                        t = float(parts[1])
                    except ValueError:
                        continue

                    value_map = {}
                    parse_ok = True
                    for idx, name in enumerate(headers[2:], start=2):
                        try:
                            value_map[name] = float(parts[idx])
                        except (ValueError, IndexError):
                            parse_ok = False
                            break

                    if not parse_ok:
                        continue

                    times.append(t)
                    for name in headers[2:]:
                        series[name].append(value_map[name])

            if not times:
                return None

            # Deduplicate potential repeated rows from repeated table blocks.
            dedup_times = []
            dedup_series = {k: [] for k in series}
            last_t = None
            for idx, t in enumerate(times):
                if last_t is not None and t == last_t:
                    continue
                dedup_times.append(t)
                for name in dedup_series:
                    dedup_series[name].append(series[name][idx])
                last_t = t

            plt.figure(figsize=(20, 6))
            for name, values in dedup_series.items():
                if values:
                    plt.plot(dedup_times, values, label=name)

            plt.xlabel("Time")
            plt.ylabel("Voltage/Current")
            plt.title("Ngspice Waveform")
            if any(len(v) > 0 for v in dedup_series.values()):
                plt.legend()
            plt.grid(True)
            plt.tight_layout()
            
            image_path = os.path.join(self.temp_dir, "waveform.png")
            plt.savefig(image_path)
            plt.close()
            
            return image_path
            
        except Exception as e:
            print(f"Error generating Ngspice plot: {e}")
            return None
    
    def cleanup(self):
        """Clean up temporary files"""
        import shutil
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass
