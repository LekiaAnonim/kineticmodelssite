#!/usr/bin/env python3
"""
Generate a simplified database schema diagram - ideal for PowerPoint overview slides.

Usage:
    python generate_schema_simple.py

Output:
    importer_dashboard_schema_simple.png
"""

import graphviz


def create_simple_schema():
    """Create a simplified schema showing main entities and relationships."""
    
    dot = graphviz.Digraph(
        'Importer Dashboard Schema (Simplified)',
        format='png',
        engine='dot'
    )
    
    # PowerPoint-optimized settings
    dot.attr(
        rankdir='LR',
        splines='polyline',
        nodesep='1.0',
        ranksep='2.0',
        bgcolor='white',
        fontname='Arial',
        fontsize='20',
        label='RMG Importer Dashboard - Database Schema',
        labelloc='t',
        labeljust='c',
        fontcolor='#1e293b',
        pad='1.0',
        dpi='200',
        size='14,8!',
        ratio='fill'
    )
    
    # Modern color palette
    colors = {
        'core': '#3b82f6',       # Blue
        'species': '#8b5cf6',    # Purple  
        'vote': '#f59e0b',       # Amber
        'chemkin': '#ef4444',    # Red
        'log': '#10b981',        # Emerald
    }
    
    def create_box(name, subtitle, color, count=''):
        """Create a styled node for a model."""
        return f'''<
        <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="12">
            <TR>
                <TD BGCOLOR="{color}" STYLE="rounded" ALIGN="CENTER">
                    <FONT COLOR="white" FACE="Arial Bold" POINT-SIZE="16"><B>{name}</B></FONT>
                    <BR/><FONT COLOR="#ffffffcc" FACE="Arial" POINT-SIZE="11">{subtitle}</FONT>
                    {f'<BR/><FONT COLOR="#ffffffaa" FACE="Arial" POINT-SIZE="9">{count}</FONT>' if count else ''}
                </TD>
            </TR>
        </TABLE>
        >'''
    
    # Main entities as clean boxes
    dot.node('User', create_box('User', 'Django Auth', '#64748b'), shape='none')
    dot.node('Config', create_box('ImportJobConfig', 'SSH/SLURM Settings', colors['core']), shape='none')
    dot.node('Job', create_box('ClusterJob', 'Import Session', colors['core']), shape='none')
    dot.node('Species', create_box('Species', 'Chemkin Species', colors['species']), shape='none')
    dot.node('Candidate', create_box('CandidateSpecies', 'RMG Match Candidates', colors['species']), shape='none')
    dot.node('Vote', create_box('Vote', 'Reaction-based Evidence', colors['vote']), shape='none')
    dot.node('ThermoMatch', create_box('ThermoMatch', 'Library Matches', colors['vote']), shape='none')
    dot.node('Reaction', create_box('ChemkinReaction', 'Mechanism Reactions', colors['chemkin']), shape='none')
    dot.node('Thermo', create_box('ChemkinThermo', 'NASA Polynomials', colors['chemkin']), shape='none')
    dot.node('Log', create_box('JobLog / SyncLog', 'Tracking, History', colors['log']), shape='none')
    
    # Edge styling
    edge_style = {
        'color': '#94a3b8',
        'penwidth': '2.5',
        'arrowhead': 'vee',
        'arrowsize': '1.2',
        'fontname': 'Arial',
        'fontsize': '10',
        'fontcolor': '#64748b'
    }
    
    # Core relationships
    dot.edge('Job', 'Config', label=' uses ', **edge_style)
    dot.edge('Job', 'User', label=' started by ', **edge_style)
    dot.edge('Species', 'Job', label=' belongs to ', **edge_style)
    dot.edge('Candidate', 'Species', label=' matches ', **edge_style)
    dot.edge('Vote', 'Species', label=' for ', **edge_style)
    dot.edge('Vote', 'Candidate', label=' supports ', **edge_style)
    dot.edge('ThermoMatch', 'Species', label=' for ', **edge_style)
    dot.edge('ThermoMatch', 'Candidate', label=' confirms ', **edge_style)
    dot.edge('Reaction', 'Job', label=' from ', **edge_style)
    dot.edge('Thermo', 'Species', label=' for ', **edge_style)
    dot.edge('Log', 'Job', label=' tracks ', **edge_style)
    
    # Subgraphs for visual grouping
    with dot.subgraph(name='cluster_core') as c:
        c.attr(label='Core', style='rounded,dashed', color='#cbd5e1', fontname='Arial', fontsize='12', fontcolor='#64748b')
        c.node('User')
        c.node('Config')
        c.node('Job')
    
    with dot.subgraph(name='cluster_matching') as c:
        c.attr(label='Species Matching', style='rounded,dashed', color='#c4b5fd', fontname='Arial', fontsize='12', fontcolor='#7c3aed')
        c.node('Species')
        c.node('Candidate')
    
    with dot.subgraph(name='cluster_evidence') as c:
        c.attr(label='Match Evidence', style='rounded,dashed', color='#fcd34d', fontname='Arial', fontsize='12', fontcolor='#b45309')
        c.node('Vote')
        c.node('ThermoMatch')
    
    with dot.subgraph(name='cluster_data') as c:
        c.attr(label='CHEMKIN Data', style='rounded,dashed', color='#fca5a5', fontname='Arial', fontsize='12', fontcolor='#b91c1c')
        c.node('Reaction')
        c.node('Thermo')
    
    # Save
    output_path = 'importer_dashboard_schema_simple'
    dot.render(output_path, cleanup=True)
    print(f"✅ Simplified schema saved to: {output_path}.png")


if __name__ == '__main__':
    create_simple_schema()
