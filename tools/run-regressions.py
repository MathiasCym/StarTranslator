"""Run document, maintenance and team tests against source or the delivered runtime."""
import importlib,json,os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
packaged='--packaged' in sys.argv
if packaged:
    resources=root/'dist/win-unpacked/resources';sys.path.insert(0,str(resources/'app.asar.unpacked'));os.environ['STAR_RESOURCE_DIR']=str(resources)
    import backend
    from backend import workflow,translation,officecli_bridge,team_sync,model_profiles,atomic_file
    assert all(str(resources/'app.asar.unpacked') in str(module.__file__) for module in (backend,workflow,translation,officecli_bridge,team_sync,model_profiles,atomic_file))
else:sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'tests'))
names=['test_text_integrity','test_word_numbering','test_word_coverage','test_quality_gate','test_pptx_layout','test_pptx_visual_review','test_pdf_residual','test_officecli_runtime','test_document_skills','test_translation_recovery','test_workflow','test_file_formats','test_maintenance_status','test_async_lan','test_document_preview','test_bit_depth','test_team_sync','test_public_sources','test_model_profiles','test_atomic_file','test_consistency','test_llm_client','test_model_transport_batches']
names+=['test_glossary_categories','test_glossary_exchange','test_glossary_formats','test_glossary_excel_format']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in names)
result=unittest.TextTestRunner(verbosity=2).run(suite)
folder=root/'dist/qa/release-200';folder.mkdir(parents=True,exist_ok=True)
(folder/('backend-result.json' if packaged else 'source-backend-result.json')).write_text(json.dumps({'passed':result.wasSuccessful(),'packaged':packaged,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'companyDocumentsSent':False},indent=2),encoding='utf-8')
sys.exit(0 if result.wasSuccessful() else 1)
