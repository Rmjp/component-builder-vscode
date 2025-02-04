from compbuilder import Component, Signal
from compbuilder import w
from compbuilder.visual import VisualMixin
from compbuilder.visual_layouts import (
    NandLayoutMixin,
    BufferLayoutMixin,
    NotLayoutMixin,
    AndLayoutMixin,
    OrLayoutMixin,
    XorLayoutMixin,
)

class VisualComponent(VisualMixin, Component):
    pass


class Nand(NandLayoutMixin,VisualComponent):
    IN = [w.a, w.b]
    OUT = [w.out]

    PARTS = []

    def process(self, a, b):
        if (a.get()==1) and (b.get()==1):
            return {'out': Signal(0)}
        else:
            return {'out': Signal(1)}
    process_interact = process
    process_interact.js = {
        'out' : 'function(w) { return (w.a==1) && (w.b==1) ? 0 : 1; }',
    }


class Buffer(BufferLayoutMixin,VisualComponent):
    IN = [w.In]
    OUT = [w.out]
    PARTS = []

    def process(self, In):
        return {'out': Signal(In.get())}
    process_interact = process
    process_interact.js = {
        'out' : 'function(w) { return w.In; }',
    }


class Not(NotLayoutMixin,VisualComponent):
    IN = [w.In]
    OUT = [w.out]

    PARTS = [
        Nand(a=w.In, b=w.In, out=w.out),
    ]


class And(AndLayoutMixin,VisualComponent):
    IN = [w.a, w.b]
    OUT = [w.out]

    PARTS = [
        Nand(a=w.a, b=w.b, out=w.c),
        Not(In=w.c, out=w.out),
    ]


class Or(OrLayoutMixin,VisualComponent):
    IN = [w.a, w.b]
    OUT = [w.out]

    PARTS = [
        Not(In=w.a, out=w.na),
        Not(In=w.b, out=w.nb),
        Nand(a=w.na, b=w.nb, out=w.out),
    ]


class Xor(XorLayoutMixin,VisualComponent):
    IN = [w.a, w.b]
    OUT = [w.out]

    PARTS = [
        Not(In=w.a, out=w.na),
        Not(In=w.b, out=w.nb),
        And(a=w.a, b=w.nb, out=w.and1),
        And(a=w.b, b=w.na, out=w.and2),
        Or(a=w.and1, b=w.and2, out=w.out),
    ]


class HalfAdder(VisualComponent):
    IN = [w.a, w.b]
    OUT = [w.s, w.carry]

    PARTS = [
        Xor(a=w.a, b=w.b, out=w.s),
        And(a=w.a, b=w.b, out=w.carry),
    ]
    

class FullAdder(VisualComponent):
    IN = [w.a, w.b, w.carry_in]
    OUT = [w.s, w.carry_out]

    PARTS = [
        HalfAdder(a=w.a,
                  b=w.b,
                  s=w.s1,
                  carry=w.c1),
        HalfAdder(a=w.carry_in,
                  b=w.s1,
                  s=w.s,
                  carry=w.c2),
        Or(a=w.c1,
           b=w.c2,
           out=w.carry_out),
    ]


class And2(VisualComponent):
    IN = [w(2).a, w(2).b]
    OUT = [w(2).out]

    PARTS = [
        And(a=w(2).a[0], b=w(2).b[0],
             out=w(2).out[0]),
        And(a=w(2).a[1], b=w(2).b[1],
             out=w(2).out[1]),
    ]


class And8(VisualComponent):
    IN = [w(8).a, w(8).b]
    OUT = [w(8).out]

    PARTS = None

    def init_parts(self):
        if And8.PARTS:
            return

        And8.PARTS = []
        for i in range(8):
            And8.PARTS.append(And(a=w(8).a[i], b=w(8).b[i],
                                  out=w(8).out[i]))


class DFF(VisualComponent):
    IN = [w.In,w.clk]
    OUT = [w.out]

    PARTS = []
    TRIGGER = [w.clk]
    LATCH = [w.out]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clk = Signal(0) 
        self._out = Signal(0)
        self.is_clocked_component = True
        self.saved_input_kwargs = None
    __init__.js = '''
        function(s) {
          s.clk = 0;
        }
    '''
    
    def process(self, In=None):
        if self.saved_input_kwargs == None:
            self.saved_output = {'out': Signal(0)}
        else:
            self.saved_output = {'out': self.saved_input_kwargs['In']}
        return self.saved_output

    def prepare_process(self, In):
        self.saved_input_kwargs = {'In': In}

    def process_interact(self,In,clk):
        if self._clk.get() == 0 and clk.get() == 1:
            self._out = In
        self._clk = clk
        return {'out':self._out}
    process_interact.js = {
        'out' : '''
            function(w,s) { // wires,states
              if (s.clk == 0 && w.clk == 1)
                s.out = w.In;
              s.clk = w.clk;
              return s.out;
            }''',
    }
