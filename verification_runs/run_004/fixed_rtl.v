// This Verilog code provides examples of fundamental digital logic modules:
// a 4-bit synchronous counter, a D-flip-flop, and a 2-to-1 multiplexer.
// It is intended for digital design and verification practice.
// The modules are not related to analog components like the LM741 Operational Amplifier.

module counter_4bit (
    input wire clk,          // Clock input
    input wire reset,        // Asynchronous reset (active high)
    input wire enable,       // Enable counting
    output reg [3:0] count   // 4-bit counter output
);

// Counter logic
always @(posedge clk or posedge reset) begin
    if (reset) begin
        count <= 4'b0000;    // Reset counter to 0
    end else if (enable) begin
        count <= count + 1;  // Increment counter
    end
    // If enable is low, counter holds its value (implied by non-blocking assignment outside if/else if)
end

endmodule


// Additional example: Simple D Flip-Flop
module d_flipflop (
    input wire clk,
    input wire reset,
    input wire d,
    output reg q
);

always @(posedge clk or posedge reset) begin
    if (reset)
        q <= 1'b0;
    else
        q <= d;
end

endmodule


// Example of a 2-to-1 Multiplexer
module mux_2to1 ( // Renamed from faulty_mux to reflect corrected behavior
    input wire sel,
    input wire a,
    input wire b,
    output reg out
);

always @(*) begin
    // FIX: Added an 'else' condition to explicitly define 'out' for all 'sel' states.
    // This prevents unintended latch inference and ensures standard multiplexer behavior.
    if (sel) begin
        out = a; // If sel is high, output 'a'
    end else begin
        out = b; // If sel is low, output 'b'
    end
end

endmodule