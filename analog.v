`include "disciplines.vams"
`include "constants.vams"

module modamp (inp, inn, outp);

inout inp, inn, outp;
electrical inp, inn, outp;
electrical n2, n3, n4, n5, n6, n7, n8, n9, n10, n11, n12;

// Parameters
parameter real GBP    = 1e6;
parameter real AOLDC  = 106.0;
parameter real FP2    = 3e6;
parameter real RO     = 75;
parameter real CD     = 1e-12;
parameter real RD     = 2e6;
parameter real IOFF   = 20e-9;
parameter real IB     = 80e-9;
parameter real VOFF   = 7e-4;
parameter real CMRRDC = 90.0;
parameter real FCM    = 200;
parameter real PSRT   = 5e5;
parameter real NSRT   = 5e5;
parameter real VLIMP  = 14;
parameter real VLIMN  = -14;
parameter real ILMAX  = 35e-3;
parameter real CSCALE = 50;

// Internal variables
real RP1, CP1, RP2, CP2;
real Rdiff, Voffset;
real CMRR0, CMgain, CCM;
real Slewratepositive, Slewratenegative;
real MTWOPI;

analog begin

    MTWOPI = 6.283185307179586;

    // Design equations
    Voffset = VOFF * 5;
    Rdiff   = RD / 2;
    CMRR0   = pow(10, CMRRDC/20);
    CMgain  = 1e6 / CMRR0;
    CCM     = 1.0 / (MTWOPI * 1e6 * FCM);
    RP1     = pow(10, AOLDC/20);
    CP1     = 1 / (MTWOPI * GBP);
    RP2     = 1;
    CP2     = 1 / (MTWOPI * FP2);
    Slewratepositive = PSRT / (MTWOPI * GBP);
    Slewratenegative = NSRT / (MTWOPI * GBP);

    // Input offset voltage
    I(inp, n7) <+ V(inp, n7) + Voffset;
    I(inn, n9) <+ V(inn, n9) - Voffset;

    // Input bias currents
    I(n7) <+ IB;
    I(n9) <+ IB;

    // Input current offset
    I(n7, n9) <+ IOFF/2;

    // Differential input resistance & capacitance
    I(n7, n8) <+ V(n7, n8)/Rdiff;
    I(n9, n8) <+ V(n9, n8)/Rdiff;
    I(n7, n9) <+ ddt(CD * V(n7, n9));

    // Common-mode stage
    I(n6) <+ -CMgain * V(n8);
    I(n6, n10) <+ V(n6, n10)/1e6;
    I(n6, n10) <+ ddt(CCM * V(n6, n10));

    // Differential + CM adder
    I(n11) <+ -V(n10);
    I(n11) <+ -V(n7, n9);

    // Slew rate limiting
    if (V(n11) > Slewratepositive)
        I(n12) <+ -Slewratepositive;
    else if (V(n11) < -Slewratenegative)
        I(n12) <+ Slewratenegative;
    else
        I(n12) <+ -V(n11);

    // First pole
    I(n3) <+ -V(n12);
    I(n3) <+ V(n3)/RP1;
    I(n3) <+ ddt(CP1 * V(n3));

    // Second pole
    I(n5) <+ -V(n3);
    I(n5) <+ V(n5)/RP2;
    I(n5) <+ ddt(CP2 * V(n5));

    // Current limiter
    if (V(n2, outp) >= ILMAX) begin
        I(n4) <+ -V(n5);
        I(n4) <+ CSCALE * V(n5) * (V(n2, outp) - ILMAX);
    end
    else if (V(n2, outp) <= -ILMAX) begin
        I(n4) <+ -V(n5);
        I(n4) <+ -CSCALE * V(n5) * (V(n2, outp) + ILMAX);
    end
    else begin
        I(n4) <+ -V(n5);
    end

    // Output resistance
    I(n4, n2) <+ V(n4, n2)/RO;
    I(n2, outp) <+ V(n2, outp);

    // Voltage limiter
    if (V(outp) > VLIMP) begin
        I(outp) <+ -10.0 * VLIMP;
        I(outp) <+ 10.0 * V(outp);
    end
    else if (V(outp) < VLIMN) begin
        I(outp) <+ -10.0 * VLIMN;
        I(outp) <+ 10.0 * V(outp);
    end

end

endmodule