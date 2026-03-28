// Sample 4-bit Synchronous Counter with Asynchronous Reset
// This is an example Verilog module for testing the verification agent

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
    // If enable is low, counter holds its value
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


// Example with potential issue: Missing else case
module faulty_mux (
    input wire sel,
    input wire a,
    input wire b,
    output reg out
);

always @(*) begin
    if (sel)
        out = a;
    // Missing else - could cause latch inference
end

endmodule
