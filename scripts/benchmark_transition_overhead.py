"""Synthetic local retrieval measurements; no model calls or savings claims."""
import argparse
import json
import time
import tracemalloc
from pathlib import Path
import numpy as np
from selection.v5.transition_library import JointTransitionLibrary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    results=[]
    for size in [100,1000,10000]:
        rows=[dict(record_id=str(index),source_group_id=f'g{index}',action='shore',
            history=[['ship','SUCCESS']],features=[index/size,1.],gains=[0.,.1,0.],
            outcome=dict(status='SUCCESS',predicted_quality=.7,latency_s=1.,cost=.1,
                         environment={'bandwidth_mbps':1.})) for index in range(size)]
        tracemalloc.start()
        start=time.perf_counter()
        library=JointTransitionLibrary(rows)
        build_s=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        query={key:rows[size//2][key] for key in ['action','history','features','gains']}
        timings=[]
        for iteration in range(110):
            start=time.perf_counter()
            library.sample(query,f'benchmark-{iteration}')
            elapsed=time.perf_counter()-start
            if iteration>=10:timings.append(elapsed)
        results.append(dict(library.storage_stats,build_s=build_s,
            traced_build_peak_bytes=peak,sample_p50_s=float(np.median(timings)),
            sample_p95_s=float(np.quantile(timings,.95))))
    with args.output.open('x') as handle:
        json.dump(dict(synthetic=True,model_calls=0,results=results,
            limitations='Payload is JSON bytes, not RSS. Build peak excludes input allocation. Timings cover retrieval and sampling only, not full controller. No monetary or energy savings measured.'),handle,indent=2)


if __name__=='__main__':main()
