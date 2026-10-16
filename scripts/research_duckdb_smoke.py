"""Optional DuckDB consumer; pip install duckdb. No tracker DB extension required."""
import json
from pathlib import Path
import tempfile

import duckdb
from tracker.research import Analysis
from tracker.store import Store
from tracker.portable import generation_document


def literal(path): return "'"+str(path).replace("'","''")+"'"


def main():
    with tempfile.TemporaryDirectory(prefix="jev-duckdb's-") as tmp:
        root=Path(tmp);store=Store(root/'workspace.sqlite')
        for index in range(4):
            store.ingest(dict(producer='control',rollout_id=str(index),revision=0,state='complete',
                format='generation',metadata=dict(experiment='control',generation_step=index),
                document=generation_document('Question',str(index),reward=index/2 if index<3 else None)))
        dataset=root/'data.sqlite';Analysis(store.path).database(dataset)
        con=duckdb.connect()
        try:
            con.execute('INSTALL sqlite');con.execute('LOAD sqlite')
            con.execute('SET sqlite_all_varchar=true')
            con.execute('ATTACH '+literal(dataset)+' AS evidence (TYPE SQLITE, READ_ONLY)')
            assert con.execute('SELECT count(*) FROM evidence.rl_rollouts').fetchone()[0]==4
            con.execute('''CREATE TABLE reward AS SELECT r.run_id,
                CAST(r.generation_step AS BIGINT) AS generation_step,
                CAST(m.value AS DOUBLE) AS "value",m.status,m.source_hash
                FROM evidence.rl_rollouts r JOIN evidence.rl_measurements m USING(run_id)
                WHERE m.metric='recorded_reward' AND m.observer='source' ''')
            parquet=root/'reward.parquet'
            con.execute('COPY reward TO '+literal(parquet)+' (FORMAT PARQUET)')
            observed=con.execute('SELECT generation_step,value FROM read_parquet(?) ORDER BY generation_step',[str(parquet)]).fetchall()
            assert observed==[(0,0.),(1,.5),(2,1.),(3,None)],observed
            assert con.execute('''SELECT count(*) FROM evidence.rl_edges e LEFT JOIN evidence.rl_nodes n
                ON n.graph_id=e.graph_id AND n.node_id=e.source WHERE n.node_id IS NULL''').fetchone()[0]==0
            print(json.dumps(dict(duckdb=duckdb.__version__,rows=len(observed),
                graph_endpoints='preserved',parquet='typed numeric and null round trip',model_calls=0)))
        finally:con.close()
    print('PASS: optional DuckDB SQLite read and typed Parquet export')


if __name__=='__main__':main()
