"""Shared sections that every resume rewrite must preserve verbatim."""
from copy import deepcopy
import hashlib
import json
import re


def is_academic_distinctions(text):
    return re.sub(r'\s+', ' ', text).strip().rstrip(':').strip().casefold() == 'academic distinctions'


def academic_paragraph_indexes(doc, is_section):
    result=set(); active=False
    for index, paragraph in enumerate(doc.paragraphs):
        if is_academic_distinctions(paragraph.text):
            active=True
        elif is_section(paragraph):
            active=False
        if active:result.add(index)
    return result


def academic_sections_preserved(source_doc, output_doc, is_section):
    """Compare the complete protected paragraph XML, including its run styling."""
    def state(element):
        # Expanded names/attributes preserve actual XML content and styling;
        # unused inherited namespace declarations are serialization details.
        return (element.tag,tuple(sorted(element.attrib.items())),element.text,element.tail,
                tuple(state(child) for child in element))
    def snapshot(doc):
        indexes=academic_paragraph_indexes(doc,is_section)
        return [state(p._p) for i,p in enumerate(doc.paragraphs) if i in indexes]
    return snapshot(source_doc)==snapshot(output_doc)


def exclude_academic_inventory(inventory, protected_indexes=None):
    """Also handles archived inventories made before this section was excluded."""
    protected={b['bullet_id'] for b in inventory['bullets']
               if is_academic_distinctions(b.get('section',''))}
    protected.update(b['bullet_id'] for group in inventory['groups']
                     if is_academic_distinctions(group.get('section','')) for b in group['bullets'])
    if protected_indexes is not None:
        protected.update(b['bullet_id'] for b in inventory['bullets']
                         if b['paragraph_index'] in protected_indexes)
    kept=[b for b in inventory['bullets'] if b['bullet_id'] not in protected]
    preserved={b['bullet_id']:deepcopy(b) for b in inventory.get('preserved_bullets',[])}
    preserved.update({b['bullet_id']:deepcopy(b) for b in inventory['bullets'] if b['bullet_id'] in protected})
    groups=[]
    for group in inventory['groups']:
        bullets=[b for b in group['bullets'] if b['bullet_id'] not in protected]
        if bullets:groups.append({**group,'bullets':bullets})
    return {**inventory,'bullets':kept,'groups':groups,'preserved_bullets':list(preserved.values()),
            'inventory_hash':hashlib.sha256(json.dumps(kept,sort_keys=True).encode()).hexdigest(),
            'errors':[error for error in inventory.get('errors',[]) if error.get('bullet_id') not in protected]}
