module parity_v1 (
input a,
input b,
output parity
);
assign parity = a ^ b;
endmodule