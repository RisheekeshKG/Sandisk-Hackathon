// Combinational Logic Circuit with Multiple Gates
module combo_circuit (out, a, b, c);
    input a, b, c;
    output out;
    
    wire and_out, or_out, xor_out;
    
    // AND gate
    assign and_out = a & b;
    
    // OR gate
    assign or_out = b | c;
    
    // XOR gate
    assign xor_out = a ^ c;
    
    // Final output: (a AND b) OR (b OR c) XOR (a XOR c)
    assign out = (and_out | or_out) ^ xor_out;
endmodule


module tb;
    reg a, b, c;
    wire out;

    combo_circuit uut(out, a, b, c);

    initial begin
        // THIS CREATES THE VCD FILE
        $dumpfile("combo_waveform.vcd");
        $dumpvars(0, tb);

        // Test all combinations
        a = 0; b = 0; c = 0; #10;
        a = 0; b = 0; c = 1; #10;
        a = 0; b = 1; c = 0; #10;
        a = 0; b = 1; c = 1; #10;
        a = 1; b = 0; c = 0; #10;
        a = 1; b = 0; c = 1; #10;
        a = 1; b = 1; c = 0; #10;
        a = 1; b = 1; c = 1; #10;

        $finish;
    end
endmodule