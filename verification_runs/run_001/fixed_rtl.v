// Sample 4-bit Synchronous Counter with Synchronous Reset
// This is an example Verilog module for testing the verification agent

module counter_4bit (
    input wire clk,          // Clock input
    input wire reset,        // Synchronous reset (active high)
    input wire enable,       // Enable counting
    output reg [3:0] count   // 4-bit counter output
);

// Counter logic with synchronous reset
// FIX: Converted asynchronous reset to synchronous reset.
// The 'reset' signal is now checked on the positive edge of the clock.
always @(posedge clk) begin
    if (reset) begin
        count <= 4'b0000;    // Reset counter to 0 synchronously
    end else if (enable) begin
        count <= count + 1;  // Increment counter
    end
    // If enable is low, counter holds its value
end

endmodule


// Additional example: Simple D Flip-Flop with Synchronous Reset
module d_flipflop (
    input wire clk,
    input wire reset,
    input wire d,
    output reg q
);

// FIX: Converted asynchronous reset to synchronous reset.
// The 'reset' signal is now checked on the positive edge of the clock.
always @(posedge clk) begin
    if (reset)
        q <= 1'b0; // Reset Q to 0 synchronously
    else
        q <= d;
end

endmodule


// Example with potential issue: Missing else case - FIXED
module faulty_mux (
    input wire sel,
    input wire a,
    input wire b,
    output reg out
);

// FIX: Added an 'else' clause to ensure 'out' is assigned a value
// for all possible 'sel' conditions, preventing latch inference.
always @(*) begin
    if (sel)
        out = a;
    else // When sel is low, output 'b'
        out = b;
end

endmodule


// FIX: Implemented the 'parity_generator' module as specified in the datasheet.
// This module calculates parity = a XOR b.
module parity_generator (
    input wire a,
    input wire b,
    output wire parity
);

    // Parity is the XOR sum of inputs a and b
    assign parity = a ^ b;

endmodule