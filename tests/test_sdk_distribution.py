"""Bounded offline checks for SDK provenance and component-only consent."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from global_pulse import distribution_terms as terms

SPEC = importlib.util.spec_from_file_location('sdk_distribution', Path(__file__).parents[1]/'scripts/sdk_distribution.py')
sdk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sdk)


def record(data):
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    bundle=tmp_path/'bundle'; bundle.mkdir()
    assets={name:(b'reviewed-test-bytes-'+name.encode()) for name in sdk.ASSETS}
    documents={name:('TEST FIXTURE '+name).encode() for name in sdk.DOCUMENTS}
    monkeypatch.setattr(sdk,'SDK_ASSET_PINS',{name:record(data) for name,data in assets.items()})
    archive=b'FAKE NUGET ARCHIVE FOR UNIT TEST ONLY'
    monkeypatch.setattr(sdk,'SDK_ARCHIVE_SHA256',record(archive)['sha256'])
    monkeypatch.setattr(sdk,'SDK_LICENSE_SHA256',record(documents['SDK_LICENSE.rtf'])['sha256'])
    for name,data in documents.items(): (bundle/name).write_bytes(data)
    manifest={'sdk_version':sdk.SDK_VERSION,'sdk_archive_sha256':sdk.SDK_ARCHIVE_SHA256,
              'documents':{n:record(d) for n,d in documents.items()},'assets':{n:record(d) for n,d in assets.items()}}
    (bundle/'BUNDLE.json').write_text(json.dumps(manifest))
    nuget=tmp_path/'nuget'; package=nuget/'microsoft.windows.sdk.net.ref'/sdk.SDK_VERSION
    (package/'lib/net8.0').mkdir(parents=True)
    (package/('microsoft.windows.sdk.net.ref.'+sdk.SDK_VERSION+'.nupkg')).write_bytes(archive)
    published=tmp_path/'published'; published.mkdir()
    for name,data in assets.items():
        (package/'lib/net8.0'/name).write_bytes(data)
        (published/name).write_bytes(data)
    deps=published/'GlobalPulse.Notifications.deps.json'
    deps.write_text(json.dumps({'targets':{'.NETCoreApp,Version=v10.0/win-x64':{
        sdk.SDK_ID:{'runtime':{name:{} for name in assets}}
    }}}))
    (published/'licenses').mkdir()
    notices={'packages':[{'package':sdk.SDK_ID.split('/')[0],'version':sdk.SDK_VERSION,
                         'evidence_kind':'external_license_reference_only','notice_files':[]}],
             'external_license_reference_only':[]}
    (published/'licenses/NATIVE_PACKAGE_NOTICES.json').write_text(json.dumps(notices))
    return bundle,nuget,package,published,deps


def prepare(fixture):
    bundle,nuget,package,published,deps=fixture
    return sdk.prepare(deps,nuget,published,bundle_root=bundle)


def test_exact_original_and_published_assets_are_verified(fixture):
    result=prepare(fixture)
    assert result['status']=='ENGINEERING_BYTE_AND_DOCUMENT_CHECK_PASS'
    assert len(result['verified_runtime_files'])==2
    assert all(x['unmodified_from_exact_nuget'] for x in result['verified_runtime_files'])
    assert result['public_release']=='NOT_APPROVED'
    published=fixture[3]
    notices=json.loads((published/'licenses/NATIVE_PACKAGE_NOTICES.json').read_text())
    assert notices['packages'][0]['evidence_kind']=='official_sdk_license_redist_and_exact_unmodified_assets'
    assert notices['external_license_reference_only']==[]
    assert (published/'licenses/windows-sdk/SDK_LICENSE.rtf').read_bytes()==(fixture[0]/'SDK_LICENSE.rtf').read_bytes()


@pytest.mark.parametrize('where',['published','original','archive'])
def test_changed_microsoft_bytes_fail_closed(fixture,where):
    bundle,nuget,package,published,deps=fixture
    path={'published':published/'Microsoft.Windows.SDK.NET.dll',
          'original':package/'lib/net8.0/Microsoft.Windows.SDK.NET.dll',
          'archive':package/('microsoft.windows.sdk.net.ref.'+sdk.SDK_VERSION+'.nupkg')}[where]
    path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='differs|mismatch'): prepare(fixture)


def test_unknown_sdk_version_is_not_granted_the_known_route(fixture):
    deps=fixture[4]
    deps.write_text(deps.read_text().replace(sdk.SDK_VERSION,'10.0.19041.58'))
    with pytest.raises(ValueError,match='Unreviewed'): prepare(fixture)


def test_unlisted_sdk_runtime_asset_is_rejected(fixture):
    deps=fixture[4]; document=json.loads(deps.read_text())
    next(iter(document['targets'].values()))[sdk.SDK_ID]['runtime']['Unexpected.dll']={}
    deps.write_text(json.dumps(document))
    with pytest.raises(ValueError,match='Unreviewed SDK runtime asset'): prepare(fixture)


def test_unknown_native_asset_is_rejected(fixture):
    deps=fixture[4]; document=json.loads(deps.read_text())
    next(iter(document['targets'].values()))[sdk.SDK_ID]['native']={'Unexpected.dll':{}}
    deps.write_text(json.dumps(document))
    with pytest.raises(ValueError,match='Unexpected native'): prepare(fixture)


@pytest.mark.parametrize('name',sorted(sdk.DOCUMENTS))
def test_changed_license_or_notice_is_not_silently_packaged(fixture,name):
    (fixture[0]/name).write_text('modified')
    with pytest.raises(ValueError,match='mismatch'): prepare(fixture)


def test_original_license_pin_cannot_be_replaced_by_manifest(fixture):
    path=fixture[0]/'BUNDLE.json'; document=json.loads(path.read_text())
    document['documents']['SDK_LICENSE.rtf']['sha256']='0'*64
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError,match='governing license'): prepare(fixture)


def test_sdk_notice_inventory_cannot_omit_projection(fixture):
    (fixture[3]/'licenses/NATIVE_PACKAGE_NOTICES.json').write_text('{"packages":[]}')
    with pytest.raises(ValueError,match='absent or duplicated'): prepare(fixture)


def term_package(tmp_path,text='Terms fixture; Microsoft component only'):
    folder=tmp_path/'notifications/licenses/windows-sdk'; folder.mkdir(parents=True,exist_ok=True)
    data=text.encode()
    (folder/'SDK_TERMS.txt').write_bytes(data)
    (folder/'BUNDLE.json').write_text(json.dumps({'sdk_version':'10.0.19041.57','documents':{'SDK_TERMS.txt':record(data)}}))
    return tmp_path


@pytest.mark.parametrize('answer',[False,None,'yes',1])
def test_only_explicit_true_records_component_consent(tmp_path,answer):
    root=term_package(tmp_path); saved={}; prompts=[]
    assert not terms.consent(root,saved.get,saved.__setitem__,lambda text:prompts.append(text) or answer)
    assert prompts and saved=={}


def test_accepted_exact_terms_are_remembered_locally(tmp_path):
    root=term_package(tmp_path); saved={}; prompts=[]
    assert terms.consent(root,saved.get,saved.__setitem__,lambda text:prompts.append(text) or True)
    assert saved[terms.SETTING]==terms.read_terms(root)[1]
    assert terms.consent(root,saved.get,saved.__setitem__,lambda text:pytest.fail('must not reprompt unchanged terms'))
    assert len(prompts)==1


def test_changed_terms_require_new_explicit_acceptance(tmp_path):
    root=term_package(tmp_path); saved={}
    assert terms.consent(root,saved.get,saved.__setitem__,lambda text:True)
    previous=saved[terms.SETTING]
    term_package(tmp_path,'Changed Microsoft terms fixture')
    assert not terms.consent(root,saved.get,saved.__setitem__,lambda text:False)
    assert saved[terms.SETTING]==previous


def test_terms_integrity_failure_never_prompts_or_accepts(tmp_path):
    root=term_package(tmp_path); saved={}
    (root/'notifications/licenses/windows-sdk/SDK_TERMS.txt').write_text('changed behind manifest')
    with pytest.raises(ValueError,match='do not match'):
        terms.consent(root,saved.get,saved.__setitem__,lambda text:pytest.fail('must fail before prompt'))
    assert saved=={}


def test_actual_packaging_bundle_is_pinned_to_official_license():
    bundle=sdk.load_bundle(sdk.BUNDLE_ROOT)
    assert bundle['documents']['SDK_LICENSE.rtf']['sha256']==sdk.SDK_LICENSE_SHA256
    text=(sdk.BUNDLE_ROOT/'SDK_TERMS.txt').read_text(encoding='utf-8')
    assert 'MICROSOFT SOFTWARE LICENSE TERMS' in text
    assert 'LGPL' in text and 'free of charge' in text


def test_main_gates_helper_start_but_not_news_monitoring():
    source=(Path(__file__).parents[1]/'global_pulse/__main__.py').read_text(encoding='utf-8')
    assert 'if accept_windows_sdk_terms(controller, window):\n                notifier.start()' in source
    assert source.index('if accept_windows_sdk_terms(controller, window):')<source.index('if args.no_start:',source.index('def begin():'))
    assert 'controller.start()' in source
