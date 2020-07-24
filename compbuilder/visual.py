import re
import math
from copy import deepcopy
from textwrap import indent,dedent
import json
import compbuilder.flatten

DEFAULT_LAYOUT_CONFIG = {
    'width' : 60,
    'port_spacing' : 20,
    'label_width' : 50,
    'label_height' : 10,
    'port_width' : 8,
    'port_height' : 8,
    'connector_width' : 20,
    'connector_height' : 16,
}

COMPOUND_GATE_JS_TEMPLATE = indent(dedent('''
  "{name}" : {{
    IN: [{inputs}],
    OUT: [{outputs}],
  }}'''),'  ')

PRIMITIVE_GATE_JS_TEMPLATE = indent(dedent('''
  "{name}" : {{
    IN: [{inputs}],
    OUT: [{outputs}],
    process: {{
  {process}
    }}
  }}'''),'  ')

PROCESS_JS_TEMPLATE = ' '*4 + '"{pin}" : {function},'

################################
def _generate_net_wiring(net_wiring,netmap):
    net,nslice = net_wiring
    start,stop,_ = nslice.indices(net.width)
    return {
        'net' : netmap[net],
        'slice' : [stop-1,start],
    }

################################
def _generate_wiring(comp,netmap):
    wiring = {}
    for w in comp.IN + comp.OUT:
        wiring[w.name] = _generate_net_wiring(
                comp.wiring[w.get_key()],netmap)
    return wiring

################################
def get_wire_name(wire):
    '''
    Generate a string representing a signal from the specified wire with
    proper slicing notation
    >>> get_wire_name(w.a)
    'a'
    >>> get_wire_name(w(8).a)
    'a[0..7]'
    >>> get_wire_name(w(8).a[2])
    'a[2]'
    >>> get_wire_name(w(8).a[2:3])
    'a[2]'
    >>> get_wire_name(w(8).a[1:5])
    'a[1..4]'
    '''
    if wire.slice:
        start,stop,_ = wire.slice.indices(wire.width)
    else:
        start = 0
        stop = wire.width
    if wire.width == 1:
        return wire.name
    elif start+1 == stop:
        return f'{wire.name}[{start}]'
    else:
        return f'{wire.name}[{start}..{stop-1}]'
        
################################
def get_wire_slice(wire):
    '''
    Generate a tuple containing the specified wire's name and its slice
    information
    >>> get_wire_slice(w.a)
    (0, 1)
    >>> get_wire_slice(w(8).a)
    (0, 8)
    >>> get_wire_slice(w(8).a[2])
    (2, 3)
    >>> get_wire_slice(w(8).a[2:3])
    (2, 3)
    >>> get_wire_slice(w(8).a[1:5])
    (1, 5)
    '''
    if wire.slice is None:
        start,stop = 0,wire.width
    else:
        start,stop,_ = wire.slice.indices(wire.width)
    return (start,stop)

################################
class VisualMixin:

    ################
    def _create_body(self,comp_id):
        body = {
            'id' : f'{comp_id}',
            'width' : self.config['width'],
            'height' : self.config['height'],
        }

        # add component label only when not empty
        if 'label' in self.config:
            body['labels'] = [{
                'text' : self.config['label'],
                'id' : f'L{comp_id}',
                'width' : self.config['label_width'],
                'height' : self.config['label_height'],
            }]

        # attach custom svg elements, if available
        if 'svg' in self.config:
            body['svg'] = self.config['svg']
        return body

    ################
    def _create_label(self,comp_id):
        label = self.config['label']
        return [{
            'text': label,
            'id': f'L{comp_id}',
            'width': 6*len(label),
            'height': self.config['label_height']
        }]

    ################
    def _create_port(self,wire,port_id,index,dir):
        side = {'in': 'WEST','out':'EAST'}[dir]
        port = {
            'id': f'P:{port_id}',
            'properties': {
              'port.side': side,
              'port.index': index,
            },
            'width': self.config['port_width'],
            'height': self.config['port_height'],
        }
        try:  # use configured port label if available
            label = self.config['ports'][wire.name]['label']
        except KeyError:
            label = wire.name

        if wire.width > 1:
            label += f'[{0}..{wire.width-1}]'

        if label:
            port['labels'] = [{
                'id' : f'LP{port_id}',
                'text' : label,
                'width' : 6*len(label),
                'height' : self.config['label_height'],
            }]

        return port

    ################
    def _create_connector(self,dir,port_id,text='',type='connector'):
        port_side = {'in':'EAST','out':'WEST'}[dir]
        if text:
            width = int(6*len(text)) + 16  # XXX magic
        else:
            width = self.config['connector_width']
        height = self.config['connector_height']
        obj = {
            'id' : f'C:{port_id}',
            'type' : type,
            'direction' : dir,
            'width' : width,
            'height' : height,
            'ports' : [{
                'id': f'CP:{port_id}',
                'properties': {
                  'port.side': port_side,
                },
                'width': 0,
                'height': 0,
                'type': 'connector',
            }],
            'properties': {
                'portConstraints': 'FIXED_ORDER',
                'nodeLabels.placement': '[H_CENTER, V_CENTER, INSIDE]'
            },
        }
        if text:
            obj['labels'] = [{
                'text': text,
                'id': f'CL:{port_id}',
                'width': width,
                'height': height,
            }]
        return obj

    ################
    def _create_edge(self,src,dst):
        return { 'sources' : [src], "targets" : [dst] }

    ################
    def _generate_elk(self,depth,netmap,base_id=''):
        self.config = deepcopy(DEFAULT_LAYOUT_CONFIG)
        # override with component's layout configuration (if exists) when it
        # is a primitive component or it is shown without internal components
        if (not self.PARTS or depth == 0) and hasattr(self,"LAYOUT_CONFIG"):
            self.config.update(self.LAYOUT_CONFIG)

        # port_map maintain mapping of (node-id,wire,slice) -> (ELK port-id)
        inner_port_map = {}
        if depth == 0 or not self.PARTS: # just create an IC box
            if 'height' not in self.config:
                # determine component's height from the maximum number of
                # ports on each side
                port_max = max(len(self.IN),len(self.OUT))
                self.config['height'] = port_max * self.config['port_spacing']
            if 'label' not in self.config:
                self.config['label'] = self.name
            box = self._create_body(self.name)
        else:
            children = []
            for i,node in self.nodes.items():
                subcomp_id = f'{base_id}_{i}'
                subcomp,inner_port_map[i] = node.component._generate_elk(depth-1,netmap,subcomp_id)
                subcomp['node_id'] = node.id
                children.append(subcomp)
            # use original label when internal components are shown
            self.config['label'] = self.name
            box = {
                'id' : self.name,
                'children' : children,
                }

        # add input and output ports to the left and right sides of the
        # component box, respectively;
        # also maintain port_map to be exposed to the outer component
        port_map = {}  # map (component's pin) -> (ELK port-id)
        elk_ports = []
        ports = [(w,'in') for w in self.IN[::-1]]
        ports += [(w,'out') for w in self.OUT]
        for i,(pin,dir) in enumerate(ports):
            port_id = f'{self.name}:{pin.name}'
            elk_port = self._create_port(pin,port_id,i,dir)
            # attach wire's net to help styling
            netwire = _generate_net_wiring(self.wiring[pin.get_key()],netmap)
            netwire['name'] = pin.name
            elk_port['wire'] = netwire
            elk_ports.append(elk_port)
            port_map[pin.get_key()] = elk_port['id']
        box['ports'] = elk_ports

        # when internal components are shown, also add edges to represent
        # internal wiring
        if depth > 0 and self.PARTS:
            # maintain a data structure that allows inquiries of an internal
            # wire's source and destination ELK ports by its name and slicing
            # wires: wire -> (net,[source...],[dest...])
            # where each source and dest is of the form (ELK-port-id,slice)
            wires = {}
            for pin in self.IN:
                _,sources,_ = wires.setdefault(pin.get_key(), 
                                (self.wiring[pin.get_key()],[],[]))
                entry = port_map[pin.get_key()], get_wire_slice(pin)
                sources.append(entry)
            for pin in self.OUT:
                _,_,dests = wires.setdefault(pin.get_key(),
                              (self.wiring[pin.get_key()],[],[]))
                entry = port_map[pin.get_key()], get_wire_slice(pin)
                dests.append(entry)
            for nid,node in self.nodes.items():
                comp = node.component
                for pin in comp.IN:
                    wire = comp.get_actual_wire(pin.name)
                    _,sources,dests = wires.setdefault(wire.get_key(),
                                        (comp.wiring[pin.get_key()],[],[]))
                    entry = inner_port_map[nid][pin.get_key()], get_wire_slice(wire)
                    dests.append(entry)
                    if wire.is_constant:
                        # constant wire; create a source connector for it
                        netwire = _generate_net_wiring(
                                comp.wiring[pin.get_key()],
                                netmap)
                        digits = math.ceil(wire.width/4)
                        connector = self._create_connector(
                                'in',
                                f'{node.component.name}:{pin.name}',
                                f'{wire.get_constant_signal().get():{digits}X}',
                                type='constant')
                        connector['wire'] = netwire
                        entry = connector['ports'][0]['id'], get_wire_slice(wire)
                        sources.append(entry)
                        box['children'].append(connector)
                for pin in comp.OUT:
                    wire = comp.get_actual_wire(pin.name)
                    _,sources,_ = wires.setdefault(wire.get_key(),
                                    (comp.wiring[pin.get_key()],[],[]))
                    entry = inner_port_map[nid][pin.get_key()], get_wire_slice(wire)
                    sources.append(entry)
            #for w in wires:
            #    print(w)
            #    sources,dests = wires[w]
            #    print(' src:', sources)
            #    print(' dst:', dests)

            # define edges from all the wire connections generated above
            edges = []
            for w,(net,sources,dests) in wires.items():
                # create an edge between source/dest with overlapping slices
                pairs = [(sport,dport) 
                           for sport,(sstart,sstop) in sources
                           for dport,(dstart,dstop) in dests
                           if sstart < dstop and dstart < sstop]

                for s,d in pairs:
                    edge = self._create_edge(s,d)
                    # attach wire's net to help styling
                    netwire = _generate_net_wiring(net,netmap)
                    edge['wire'] = netwire
                    edges.append(edge)

            # enumerate all edges and give them proper IDs
            for i,edge in enumerate(edges):
                edge['id'] = f'E{base_id}_{i}'

            # attach edges to the box
            box['edges'] = edges

        # give the box a final touch
        box['gate'] = self.get_gate_name()
        box['labels'] = self._create_label(base_id)
        box['properties'] = {
            'portConstraints': 'FIXED_ORDER',
            'nodeLabels.placement': '[H_LEFT, V_TOP, OUTSIDE]',
            'portLabels.placement': 'OUTSIDE',
        }
        return box, port_map

    ################
    def _resolve_dependencies(self):
        unexplored = [self.__class__]
        resolved = []
        resolved_set = set()
        while unexplored:
            comp = unexplored[-1]
            if comp in resolved_set: # it may have already been resolved
                unexplored.pop()
                continue
            deps = set(c.__class__ for c in comp.PARTS
                                   if c.__class__ not in resolved_set)
            if deps:
                unexplored.extend(deps)
            else:  # comp's dependencies already resolved
                resolved.append(comp)
                resolved_set.add(comp)
                unexplored.pop()
        return resolved

    ################
    @classmethod
    def _generate_part_config(cls):
        name = cls.__name__
        inputs = ','.join([f'"{w.name}"' for w in cls.IN])
        outputs = ','.join([f'"{w.name}"' for w in cls.OUT])
        if cls.PARTS:
            return COMPOUND_GATE_JS_TEMPLATE.format(
                name=name,
                inputs=inputs,
                outputs=outputs,
            )
        else:
            process = [PROCESS_JS_TEMPLATE.format(pin=k,function=v)
                        for k,v in cls.process.js.items()]
            return PRIMITIVE_GATE_JS_TEMPLATE.format(
                name=name,
                inputs=inputs,
                outputs=outputs,
                process='\n'.join(process),
            )

    ################
    def generate_elk(self,depth=0,**kwargs):
        layout,port_map = self._generate_elk(depth,self.netmap,**kwargs)

        connectors = []
        conlinks = []
        ports = [(p,'in') for p in self.IN[::-1]]
        ports += [(p,'out') for p in self.OUT]
        for i,(port,dir) in enumerate(ports):
            netwire = _generate_net_wiring(
                    self.wiring[port.get_key()],self.netmap)
            netwire['name'] = port.name
            if port.width > 1:  # generate placeholder for signal's value
                value = '0'*math.ceil(port.width/4)
            else:
                value = ''
            connector = self._create_connector(dir,f'{self.name}:{port.name}',value)
            connector['wire'] = netwire
            connectors.append(connector)
            connector_id = connector['ports'][0]['id']
            port_id = port_map[port.get_key()]
            conlink = self._create_edge(connector_id,port_id)
            conlink['id'] = f'CE:{i}'
            conlink['wire'] = netwire
            conlinks.append(conlink)

        return {
            'id' : 'root',
            'children' : [layout] + connectors,
            'edges' : conlinks,
        }

    ################
    def _generate_node_map(self,elk,node_map,prefix):
        if 'children' not in elk:
            return
        for c in elk['children']:
            part_expr = f'{prefix}.parts[{c["node_id"]}]'
            node_map[c['id']] = part_expr
            self._generate_node_map(c,node_map,part_expr)

    ################
    def _generate_component_config(self):
        # create component->index mappings
        # component list consists of the main component itself, and all its
        # primitives and wirings
        partmap = {}
        for i,part in enumerate([self] + self.primitives):
            partmap[part] = i

        # create net->index mappings
        self.netmap = {}
        for i,net in enumerate(self.netlist):
            self.netmap[net] = i

        # generate primitive component wiring 
        parts = []
        for comp in [self] + self.primitives:
            wiring = _generate_wiring(comp,self.netmap)
            parts.append({
                'name': comp.name,
                'config': comp.get_gate_name(),
                'wiring': wiring,
            })

        # generate netlist config
        nets = []
        for net in self.netlist:
            sources = []
            for source in net.sources:
                start,stop,_ = source.slice.indices(net.width)
                if (start,stop) == (0,1): # single wire; omit slicing
                    sources.append({
                        'part' : partmap[source.component],
                        'wire' : source.wire.name,
                    })
                else: 
                    sources.append({
                        'part' : partmap[source.component],
                        'wire' : source.wire.name,
                        'slice' : [stop-1,start],
                    })
            nets.append({
                'name' : net.name,
                'width' : net.width,
                'signal' : net.signal.get(),
                'sources' : sources,
                'wiring' : _generate_wiring(comp,self.netmap),
            })

        # combine all configs
        config = {
            'parts': parts,
            'nets': nets,
        }
        return config

    ################
    def generate_js(self,indent=None,depth=0,**kwargs):
        self.flatten()
        lines = []

        # main component configuration
        comp_js = json.dumps(self._generate_component_config(),indent=indent)
        lines.append('var comp_config = ' + comp_js + ';')

        # main component's wiring and all used primitives
        used_primitives = set(p.__class__ for p in self.primitives)
        part_configs_js = ','.join(p._generate_part_config()
                for p in [self.__class__]+list(used_primitives))
        lines.append('')
        lines.append('comp_config.part_configs = {' + part_configs_js + '\n};')

        # instantiate the main component
        lines.append('')
        lines.append('var component = new Component(comp_config);')

        # ELK graph
        lines.append('')
        elk = self.generate_elk(depth,**kwargs)
        lines.append('var graph = '
                + json.dumps(elk,indent=indent)
                + ';')

        ## create mapping from ELK's node id to corresponding component
        #lines.append('')
        #lines.append('var node_map = {}')
        #node_map = {}
        #self._generate_node_map(elk['children'][0],node_map,'component')
        ## create the mapping for the root component manually
        #node_map[elk['children'][0]['id']] = 'component'
        #node_map['root'] = 'component'

        #for k,v in node_map.items():
        #    lines.append(f'node_map.{k} = {v}')

        lines.append('')
        lines.append('var config = {component: component, graph: graph};');

        return '\n'.join(lines)

    
def interact(component_class,**kwargs):
    import IPython.display as DISP

    DISP.display_html(DISP.HTML("""
        <script src="https://d3js.org/d3.v5.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/elkjs@0.6.2/lib/elk.bundled.js"></script>
        <script src="https://www.cpe.ku.ac.th/~cpj/tmp/component.js"></script>
        <script src="https://www.cpe.ku.ac.th/~cpj/tmp/visual.js"></script>
    """))

    component = component_class()
    component.init_interact()
    
    DISP.display_html(
        DISP.HTML('<script>' + component.generate_js(**kwargs) + '</script>'))
    DISP.display_html(DISP.HTML("""
        <link rel="stylesheet" type="text/css" href="https://www.cpe.ku.ac.th/~cpj/tmp/styles.css" />
        <div id="diagram"></div>
        <script>
          compbuilder.create("#diagram",config);
        </script>
    """))
