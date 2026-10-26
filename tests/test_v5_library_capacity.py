from copy import deepcopy
import numpy as np
import pytest
from selection.v5.transition_library import JointTransitionLibrary
from test_v5_transitions import row,query


def test_capacity_rejects_instead_of_silently_changing_policy():
    rows=[row(index) for index in range(6)]
    with pytest.raises(ValueError,match='record capacity'):
        JointTransitionLibrary(rows,max_records=5)
    with pytest.raises(ValueError,match='payload capacity'):
        JointTransitionLibrary(rows,max_payload_bytes=1)
    library=JointTransitionLibrary(rows,max_records=6)
    assert library.storage_stats['records']==6
    assert library.storage_stats['payload_bytes']>0


@pytest.mark.parametrize('option',['max_records','max_payload_bytes'])
@pytest.mark.parametrize('value',[0,-1,True,1.5])
def test_invalid_capacity(option,value):
    with pytest.raises(ValueError):JointTransitionLibrary([row(0)],**{option:value})


def test_index_matches_scalar_distances_and_group_selection():
    rows=[row(index) for index in range(10)]
    rows[1]['source_group_id']='g0'
    unrelated=deepcopy(rows[0])
    unrelated.update(record_id='other',action='cloud')
    rows.append(unrelated)
    library=JointTransitionLibrary(rows,max_distance=100)
    probe=query()
    expected=[]
    for record in rows:
        if record['action']!='shore' or record['source_group_id']=='g3':continue
        delta=np.r_[(np.array(record['features'])-probe['features'])/library.base_scale,
                    (np.array(record['gains'])-probe['gains'])/library.gain_scale]
        expected.append((float(np.linalg.norm(delta)),record['record_id'],record['source_group_id']))
    unique=[]
    seen=set()
    for distance,record_id,group in sorted(expected):
        if group in seen:continue
        seen.add(group)
        unique.append((distance,record_id))
    actual=library.neighbors(probe,exclude_group='g3')['neighbors']
    assert [entry['record']['record_id'] for entry in actual]==[item[1] for item in unique]
    assert [entry['distance'] for entry in actual]==pytest.approx([item[0] for item in unique])
