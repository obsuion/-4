"""Independent local admission authority in the existing FULL/WAL State pool.

Portable receipts are evidence. Only a separately selected owned pool can pin
one after a trusted proof. Public catalogue hashes never establish authority.
"""
from pathlib import Path
import sqlite3
import uuid
from contextlib import contextmanager
from .data import canonical,digest,identity,no_links,read_bytes,parse,write_new
from .errors import Refusal

DDL='''CREATE TABLE IF NOT EXISTS project_import_receipts(
 closure TEXT PRIMARY KEY, owner TEXT NOT NULL, path TEXT UNIQUE NOT NULL,
 sha256 TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS project_import_attempts(
 closure TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL,
 output TEXT NOT NULL, evidence BLOB);
'''

R6='DESIGNS_R6_VERIFIED154_CORE_B68_V1'
R6_SCOPE='DATA_ADMISSION_BEFORE_NAMED_RUNTIME_V2'
R7='DESIGNS_R7_SERVICE_V2_VERIFIED154_CORE_B68_V1'
R7_SCOPE='CURRENT_V2_ALL_PACKAGE_R10_V1'
OLD_R6_AUTHORITY='21a0a2836fb85ebc590963ac2f8cf045cc35180783c2cd4a0986f9fb9eadd6e2'
OLD_R6_NAMED='25b9984296418da9d1001b332a126051714f1907962f4375ece50e5178655797'

def verifier_closure(adapter=None):
    files={p.name:digest(read_bytes(p)) for p in sorted(Path(__file__).parent.glob('*.py'))}
    # Named binding/mission execution occurs AFTER the codec proof and private
    # receipt. It is separately source-bound by each actual entry and public ACK.
    # Every other admission dependency remains pinned, including this authority.
    if adapter==R6:files.pop('named_execution.py')
    return files

def authority_body(v):
    body={k:v[k] for k in ('schema','adapter','producer','source','compiler','freeze_sha256',
        'common_projection_sha256','research_authority_sha256','common_input_sha256',
        'raw_files','codec_proof','cases')}
    if v['adapter']in ('DESIGNS_R4_CORE_B68_V1','DESIGNS_R5_CORE_B68_V1',R6,R7):body['profile_identity']=v['profile_identity']
    return body

def closure_key(v):
    if v['adapter']==R7:
        return identity(dict(schema=v['schema'],adapter=R7,compiler=v['compiler'],source=v['source'],
            raw_files=v['raw_files'],producer=v['producer'],profile_identity=v['profile_identity'],
            verifier_scope=R7_SCOPE,verifier=verifier_closure(R7)))
    if v['adapter']==R6:
        return identity(dict(schema=v['schema'],adapter=v['adapter'],compiler=v['compiler'],
            source=v['source'],raw_files=v['raw_files'],producer=v['producer'],
            profile_identity=v['profile_identity'],verifier_scope=R6_SCOPE,verifier=verifier_closure(R6)))
    if v['adapter']in ('DESIGNS_R4_CORE_B68_V1','DESIGNS_R5_CORE_B68_V1','DESIGNS_R6_VERIFIED154_CORE_B68_V1'):
        return identity(dict(schema=v['schema'],adapter=v['adapter'],compiler=v['compiler'],
            source=v['source'],raw_files=v['raw_files'],producer=v['producer'],
            profile_identity=v['profile_identity'],verifier=verifier_closure()))
    from .project_owners import registered
    p=registered(adapter=v['adapter'])
    # Bind the actual CAMPAIGN verifier implementation as well as the producer.
    verifier=verifier_closure()
    return identity(dict(schema=v['schema'],adapter=p['adapter'],compiler=p['compiler'],
        source=p['source'],raw_files=v['raw_files'],producer=v['producer'],verifier=verifier))

class ReceiptAuthority:
    def __init__(self,pool):
        self.pool=no_links(pool).resolve()
        if not self.pool.is_file():raise Refusal('OWNED_IMPORT_POOL_REQUIRED')
        with self.connection() as c:
            try:row=c.execute("SELECT value FROM meta WHERE key='project_import_owner'").fetchone()
            except sqlite3.Error as e:raise Refusal('OWNED_IMPORT_POOL_REQUIRED') from e
        if row is None:raise Refusal('OWNED_IMPORT_POOL_REQUIRED')
        self.owner=parse(bytes(row[0]))
        if type(self.owner) is not str or len(self.owner)!=32 or any(c not in '0123456789abcdef' for c in self.owner):
            raise Refusal('OWNED_IMPORT_OWNER_IDENTITY')
        self.metrics=dict(receipt_lookups=0,cache_hits=0,verified_receipt_reads=0)

    @contextmanager
    def connection(self,writable=False):
        no_links(self.pool)
        c=sqlite3.connect(self.pool if writable else self.pool.as_uri()+'?mode=ro',
            uri=not writable,timeout=5,isolation_level=None)
        if writable:c.execute('PRAGMA synchronous=FULL')
        try:yield c
        finally:c.close()

    @staticmethod
    def initialize(c):
        c.executescript(DDL)
        c.execute("INSERT OR IGNORE INTO meta VALUES('project_import_owner',?)",(canonical(uuid.uuid4().hex),))

    def lookup(self,v):
        self.metrics['receipt_lookups']+=1
        key=closure_key(v)
        with self.connection() as c:
            row=c.execute('SELECT owner,path,sha256,payload_sha256 FROM project_import_receipts WHERE closure=?',(key,)).fetchone()
        if row is None:return None
        self.metrics['cache_hits']+=1
        if row[0]!=self.owner:raise Refusal('FOREIGN_IMPORT_RECEIPT_OWNER')
        raw=read_bytes(no_links(row[1]))
        if digest(raw)!=row[2]:raise Refusal('IMPORT_RECEIPT_DATABASE_PIN')
        receipt=parse(raw)
        schema='KAZE_OWNED_PROJECT_IMPORT_RECEIPT_R10_CURRENT_V1'if v['adapter']==R7 else 'KAZE_OWNED_PROJECT_IMPORT_RECEIPT_R6_DATA_V2'if v['adapter']==R6 else 'KAZE_OWNED_PROJECT_IMPORT_RECEIPT_V1'
        if (receipt.get('schema')!=schema or receipt.get('owner')!=self.owner or
            receipt.get('closure')!=key or receipt.get('verifier_files')!=verifier_closure(v['adapter']) or identity(receipt.get('verified'))!=row[3]):
            raise Refusal('IMPORT_RECEIPT_BINDING')
        if v['adapter']==R7:
            if receipt.get('verifier_scope')!=R7_SCOPE or receipt.get('execution_grant')is not False:raise Refusal('R7_CURRENT_RECEIPT_SCOPE')
        if v['adapter']==R6:
            if receipt.get('verifier_scope')!=R6_SCOPE or receipt.get('execution_grant')is not False:raise Refusal('R6_DATA_RECEIPT_SCOPE')
            previous=receipt.get('original_admission')
            if previous is not None:self._original_r6(previous,receipt['verified'])
        return receipt

    def _original_r6(self,previous,body):
        """Only the exact already-owned V1 receipt can be a migration parent."""
        with self.connection()as c:
            row=c.execute('SELECT owner,path,sha256,payload_sha256 FROM project_import_receipts WHERE closure=?',(previous['closure'],)).fetchone()
        if row is None or row[0]!=self.owner or row[2]!=previous['sha256']or row[3]!=identity(body):raise Refusal('R6_ORIGINAL_PRIVATE_RECEIPT_PIN')
        raw=read_bytes(no_links(row[1]));old=parse(raw)
        if digest(raw)!=row[2]or old.get('schema')!='KAZE_OWNED_PROJECT_IMPORT_RECEIPT_V1'or old.get('owner')!=self.owner or old.get('verified')!=body:raise Refusal('R6_ORIGINAL_ADMISSION_BODY')
        files=old['verifier_files']
        if files.get('project_receipts.py')!=OLD_R6_AUTHORITY or files.get('named_execution.py')!=OLD_R6_NAMED:raise Refusal('R6_EXACT_ORIGINAL_AUTHORITY_REVISION')
        actual=verifier_closure(R6)
        if set(files)!=(set(actual)|{'named_execution.py'}):raise Refusal('R6_ORIGINAL_VERIFIER_MEMBERSHIP')
        if any(files[n]!=h for n,h in actual.items()if n!='project_receipts.py'):raise Refusal('R6_ADMISSION_DEPENDENCY_CHANGED_RECOMPILE_REQUIRED')
        v=body
        oldkey=identity(dict(schema=v['schema'],adapter=v['adapter'],compiler=v['compiler'],source=v['source'],
            raw_files=v['raw_files'],producer=v['producer'],profile_identity=v['profile_identity'],verifier=files))
        if oldkey!=previous['closure']or old.get('closure')!=oldkey:raise Refusal('R6_ORIGINAL_FULL_CLOSURE_KEY')
        return old

    def migrate_owned_r6_data(self,path,directory):
        """Explicit local DATA-only transition. No portable proof or new grant.

        Constructor/admission modules, CORE858, compiler154 and every raw input
        are freshly checked. Original receipt/full verifier/DB row are retained.
        Only the known authority ABI and post-admission named namespace differ.
        """
        from .current_projects import header
        from .current_profiles import registered
        from .data import inside
        v=header(path)
        if v['adapter']!=R6:raise Refusal('R6_MIGRATION_ONLY')
        registered(self,v['profile_identity'])
        for n,pin in v['raw_files'].items():
            raw=read_bytes(inside(Path(path).parent/'raw',n),8*2**20)
            if len(raw)!=pin['bytes']or digest(raw)!=pin['sha256']:raise Refusal('R6_MIGRATION_RAW_DRIFT')
        body=authority_body(v)
        with self.connection()as c:
            rows=c.execute('SELECT closure,sha256 FROM project_import_receipts WHERE owner=? AND payload_sha256=?',(self.owner,identity(body))).fetchall()
        if len(rows)!=1:raise Refusal('R6_EXACT_ONE_ORIGINAL_PRIVATE_RECEIPT_REQUIRED')
        previous=dict(closure=rows[0][0],sha256=rows[0][1]);self._original_r6(previous,body)
        key=closure_key(v);receipt=dict(schema='KAZE_OWNED_PROJECT_IMPORT_RECEIPT_R6_DATA_V2',owner=self.owner,
            closure=key,verifier_scope=R6_SCOPE,verifier_files=verifier_closure(R6),original_admission=previous,
            verified=body,dispatch=False,science_entries=0,execution_grant=False)
        raw=canonical(receipt);target=no_links(directory).absolute()/(key+'-DATA-V2-'+uuid.uuid4().hex+'.json');write_new(target,raw)
        with self.connection(True)as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                c.execute('INSERT INTO project_import_receipts VALUES(?,?,?,?,?)',(key,self.owner,str(target),digest(raw),identity(body)));c.commit()
            except BaseException:c.rollback();raise
        self.require(v)
        return dict(state='MIGRATED_OWNED_DATA_ONLY',original=previous,current=dict(closure=key,sha256=digest(raw)),
            constructor_transactions=0,constructor_units=0,science_entries=0,execution_grant=False)

    def require(self,v):
        r=self.lookup(v)
        if r is None:raise Refusal('OWNED_IMPORT_RECEIPT_REQUIRED_REVERIFY_EXPLICITLY')
        if r['verified']!=authority_body(v):raise Refusal('INDEPENDENT_INITIAL_PROOF_MISMATCH')
        self.metrics['verified_receipt_reads']+=1
        return r

    def require_historical_r6(self,queue,case_identity):
        """Typed DATA authority under the original verifier; never require()."""
        if queue.authority.pool!=self.pool or queue.authority.owner!=self.owner:
            raise Refusal('HISTORICAL_OWNED_POOL_JOIN')
        from .historical_r6 import require
        return require(queue,case_identity)[0]

    def begin(self,v,output):
        key=closure_key(v)
        with self.connection(True) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                if c.execute('SELECT state FROM project_import_attempts WHERE closure=?',(key,)).fetchone():
                    raise Refusal('IMPORT_VERIFICATION_ATTEMPT_RETAINED_NO_AUTOMATIC_RETRY')
                c.execute('INSERT INTO project_import_attempts VALUES(?,?,?,?,NULL)',
                    (key,self.owner,'VERIFYING',str(Path(output).absolute())))
                c.commit()
            except BaseException:c.rollback();raise

    def check_attempt(self,v):
        with self.connection() as c:
            if c.execute('SELECT state FROM project_import_attempts WHERE closure=?',(closure_key(v),)).fetchone():
                raise Refusal('IMPORT_VERIFICATION_ATTEMPT_RETAINED_NO_AUTOMATIC_RETRY')

    def settled_failure(self,v,evidence):
        with self.connection(True) as c:
            c.execute("UPDATE project_import_attempts SET state=?,evidence=? WHERE closure=? AND owner=? AND state='VERIFYING'",
                ('FAILED_SETTLED' if evidence.get('reaped') else 'UNKNOWN',canonical(evidence),closure_key(v),self.owner))

    def publish(self,v,directory):
        """Called only after proof/closure comparison. Orphan files grant nothing."""
        body=authority_body(v);key=closure_key(v)
        receipt=dict(schema='KAZE_OWNED_PROJECT_IMPORT_RECEIPT_R10_CURRENT_V1'if v['adapter']==R7 else 'KAZE_OWNED_PROJECT_IMPORT_RECEIPT_R6_DATA_V2'if v['adapter']==R6 else 'KAZE_OWNED_PROJECT_IMPORT_RECEIPT_V1',owner=self.owner,
            closure=key,verifier_files=verifier_closure(v['adapter']),verified=body,dispatch=False,science_entries=0)
        if v['adapter']==R6:receipt.update(verifier_scope=R6_SCOPE,original_admission=None,execution_grant=False)
        if v['adapter']==R7:receipt.update(verifier_scope=R7_SCOPE,execution_grant=False)
        raw=canonical(receipt);path=no_links(directory).absolute()/(key+'-'+uuid.uuid4().hex+'.json')
        write_new(path,raw)
        with self.connection(True) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                prior=c.execute('SELECT payload_sha256 FROM project_import_receipts WHERE closure=?',(key,)).fetchone()
                if prior and prior[0]!=identity(body):raise Refusal('CONFLICTING_TRUSTED_IMPORT_PROOF')
                if not prior:c.execute('INSERT INTO project_import_receipts VALUES(?,?,?,?,?)',
                    (key,self.owner,str(path),digest(raw),identity(body)))
                c.execute("UPDATE project_import_attempts SET state='VERIFIED' WHERE closure=? AND owner=? AND state='VERIFYING'",(key,self.owner))
                c.commit()
            except BaseException:c.rollback();raise
        return self.require(v)
