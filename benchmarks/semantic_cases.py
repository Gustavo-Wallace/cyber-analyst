"""Synthetic expectations fixed before real inference; no prompt examples."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Case:
    name: str
    csv: str
    expected_category: tuple[str, ...]
    expected_column_semantics: dict[str, tuple[str, ...]]
    expected_identifier_behavior: dict[str, bool]


def case(name, csv, category, columns):
    return Case(name, csv, tuple(category.split('|')),
                {name: tuple(types.split('|')) for name, types, identifier in columns},
                {name: identifier for name, types, identifier in columns})

ORIGINAL = (
    case('authentication', 'event_time,user_login,src_ip,result,mfa_used\n2026-09-18T02:14:00,ana,10.0.0.5,failed,true\n2026-09-18T02:15:00,ana,10.0.0.5,failed,true\n2026-09-18T02:16:00,bruno,192.168.1.20,success,false\n', 'authentication_events', [('event_time','timestamp',False),('user_login','username|user_id',True),('src_ip','ip_address',True),('result','status',False),('mfa_used','boolean|mfa_status',False)]),
    case('vulnerabilities', 'asset_hostname,cve_id,severity,cvss_score,first_seen,status\nSRV-01,CVE-2026-1234,critical,9.8,2026-08-10,open\nWS-42,CVE-2025-9911,medium,5.4,2026-07-02,open\n', 'vulnerability_data', [('asset_hostname','hostname',True),('cve_id','cve',True),('severity','severity',False),('cvss_score','risk_score',False),('first_seen','date',False),('status','status',False)]),
    case('generic', 'record_code,group_name,value_a,value_b,notes\nA12,alpha,17,3.4,reviewed\nB91,beta,21,7.8,pending\n', 'unknown', [('record_code','generic_identifier',True),('group_name','category|unknown',False),('value_a','numeric_measure',False),('value_b','numeric_measure',False),('notes','free_text|status',False)]),
)

CASES = (
    case('authentication', 'ts,principal,remote,outcome,factor\n2026-09-01T12:00:00,jsilva,2001:db8::1,login_denied,otp\n2026-09-01T12:01:00,mpires,2001:db8::2,login_success,password\n', 'authentication_events', [('ts','timestamp',False),('principal','username|user_id|account_id',True),('remote','ip_address',True),('outcome','status',False),('factor','category|mfa_status',False)]),
    case('vulnerability', 'affected_node,reference,priority,score,remediation\napp-01,CVE-2024-12345,high,8.1,patch_pending\napp-02,CVE-2025-54321,critical,9.8,patched\n', 'vulnerability_data', [('affected_node','hostname|asset_id',True),('reference','cve',True),('priority','severity',False),('score','risk_score',False),('remediation','status',False)]),
    case('identity', 'employee_ref,login_name,corporate_mail,division,account_state\nE101,jsilva,joao@example.org,Finance,enabled\nE102,mpires,maria@example.org,Operations,disabled\n', 'identity_data', [('employee_ref','user_id|generic_identifier',True),('login_name','username',True),('corporate_mail','email',True),('division','department|organizational_unit',False),('account_state','account_status|status',False)]),
    case('network', 'src,dst,dpt,proto,firewall_action\n10.1.0.2,203.0.113.2,443,TCP,allow\n10.1.0.3,203.0.113.3,22,TCP,deny\n', 'network_events', [('src','ip_address',True),('dst','ip_address',True),('dpt','port',False),('proto','protocol',False),('firewall_action','status|category',False)]),
    case('inventory', 'ci_number,node_name,platform,assigned_unit\nCI100,db-prod-01,Windows Server,Finance\nCI101,edge-02,Ubuntu,Operations\n', 'asset_inventory', [('ci_number','asset_id|generic_identifier',True),('node_name','hostname',True),('platform','category|free_text',False),('assigned_unit','department|organizational_unit',False)]),
    case('exposure', 'breach_source,mail,exposed_secret,discovered_on\npublic_leak,one@example.net,dummy-secret-A,2026-04-01\ncredential_dump,two@example.net,dummy-secret-B,2026-04-02\n', 'credential_exposure', [('breach_source','source|category',False),('mail','email',True),('exposed_secret','password|credential',False),('discovered_on','date',False)]),
    case('endpoint', 'device,process_name,command_line,event_time,file_digest\nworkstation-01,powershell.exe,powershell.exe -NoProfile,2026-04-01T10:00:00,'+'a'*64+'\nworkstation-02,python.exe,python.exe job.py,2026-04-01T11:00:00,'+'b'*64+'\n', 'endpoint_events', [('device','hostname|device_id',True),('process_name','process_name',True),('command_line','command_line',False),('event_time','timestamp',False),('file_digest','hash',True)]),
    case('alerts', 'alert_ref,detection_rule,product,priority,triage_state,resource\nAL100,Malicious download,EDR,high,new,https://example.org/a\nAL101,Credential theft,SIEM,critical,investigating,https://example.net/b\n', 'security_alerts', [('alert_ref','event_id|generic_identifier',True),('detection_rule','category|free_text',False),('product','source|category',False),('priority','severity',False),('triage_state','status',False),('resource','url',True)]),
    case('ambiguous', 'a,b,c\nred,kappa,left\nblue,omega,right\n', 'unknown', [('a','unknown|category',False),('b','unknown|category',False),('c','unknown|category',False)]),
    case('non_security', 'product_code,units_sold,unit_price,shop_city\nP001,12,19.90,Recife\nP002,8,25.50,Curitiba\n', 'unknown', [('product_code','generic_identifier',True),('units_sold','numeric_measure',False),('unit_price','numeric_measure',False),('shop_city','city',False)]),
)

FOCUSED = (
    CASES[0], CASES[1], CASES[8], CASES[9], CASES[2],
    case('hash_128', 'file_digest\n'+'a'*128+'\n'+'a'*127+'b\n', 'unknown',
         [('file_digest','hash',True)]),
)
