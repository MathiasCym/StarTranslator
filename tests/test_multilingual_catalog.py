"""Multilingual reference must not change the bilingual translation glossary."""
import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.glossary import catalog,store
from backend.glossary import language_pairs as pairs, multilingual_workbook as workbook_exchange, writer
from backend.glossary.loader import DEFAULT_PATH
from backend.server import app

class MultilingualCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'NOVATERM_DATA_DIR':self.tmp.name});env.start();self.addCleanup(env.stop)

    def test_latest_sixteen_languages_match_source_without_inventing_blank_cells(self):
        data=catalog.read()
        self.assertTrue(data['readOnly'])
        self.assertEqual(data['sourceRows'],1902)
        self.assertEqual(len(data['entries']),1902)
        self.assertEqual(len({row['id'] for row in data['entries']}),1902)
        counts={'zh-CN':1902,'en-US':1902,'es-ES':1871,'fr-FR':1871,'ja-JP':1871,'ko':1870,'pt':1871,'ru-RU':1871,
            'ar-SA':1898,'de-DE':1898,'id-ID':1898,'it-IT':1898,'th-TH':1898,'tr-TR':1898,'vi-VN':1898,'zh-Hant-TW':1899}
        self.assertEqual({lang['code']:lang['count'] for lang in data['languages']},counts)
        for code,count in counts.items():
            self.assertEqual(sum(bool(row['terms'].get(code)) for row in data['entries']),count)
        self.assertEqual(data['sourceSha256'],'c7ef5c90044eb09fc0293703f1279acc5f9502246dbcf59865ff3e6f105cb277')
        self.assertEqual(data['sourceLanguageCodes']['ko'],'ko-KR')
        self.assertEqual(data['sourceLanguageCodes']['zh-Hant-TW'],'zh-Hant-TW')

    def test_read_does_not_seed_modify_or_expand_active_translation_glossary(self):
        before=store.read();raw=Path(before['path']).read_bytes()
        rows=[entry.to_dict() for entry in store.load_glossary().entries]
        for _ in range(2):catalog.read()
        self.assertEqual(Path(before['path']).read_bytes(),raw)
        self.assertEqual([entry.to_dict() for entry in store.load_glossary().entries],rows)
        self.assertEqual(len(rows),2456)
        self.assertFalse((Path(self.tmp.name)/'multilingual.json').exists())

    def test_api_is_read_only(self):
        client=app.test_client()
        response=client.get('/api/lexicon/catalog')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['languages']),16)
        self.assertEqual(client.post('/api/lexicon/catalog',json={'entries':[]}).status_code,405)
        self.assertEqual(client.delete('/api/lexicon/catalog').status_code,405)

    def test_unavailable_catalog_does_not_break_bilingual_glossary(self):
        with patch.object(catalog,'DEFAULT_PATH',str(Path(self.tmp.name)/'missing/terms.json')):
            with self.assertRaisesRegex(ValueError,'中英词库仍可正常使用'):catalog.read()
        self.assertEqual(len(store.read()['entries']),2456)

    def test_stale_user_catalog_cannot_shadow_the_shipped_latest_catalog(self):
        stale=Path(self.tmp.name)/'multilingual.json';stale.write_text('{"entries":[],"languages":[]}',encoding='utf-8')
        data=catalog.read();self.assertEqual(len(data['languages']),16)
        self.assertEqual(len(data['entries']),1902)
        self.assertEqual(stale.read_text('utf-8'),'{"entries":[],"languages":[]}')

    def test_all_language_workbook_uses_sixteen_tabs_and_round_trips_a_draft(self):
        from openpyxl import load_workbook
        from openpyxl.utils import get_column_letter
        from backend.glossary import excel_format,language_exchange
        client=app.test_client()
        table=pairs.table('ja-JP')
        entry=['测试工作簿术语','=示例','待发布说明'*90,'测试別名','','','1','测试','term','','','','']
        table['rows'].append(entry)
        target=Path(self.tmp.name)/'all-languages.xlsx'
        result=client.post('/api/lexicon/export',json={**table,'path':str(target),'all_languages':True,'destination_fingerprint':''})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['sheets'],16)
        book=load_workbook(target)
        try:
            self.assertEqual({name.rsplit('(',1)[1][:-1] for name in book.sheetnames},{item['code'] for item in catalog.read()['languages']})
            self.assertEqual(book.loaded_theme,excel_format.preset()['theme'].encode('utf-8'))
            sheet=book.active
            self.assertTrue(sheet.title.endswith('(ja-JP)'))
            row=next(row for row in sheet.iter_rows() if row[0].value==entry[0])
            self.assertEqual((row[1].value,row[1].data_type),('=示例','s'))
            self.assertEqual(row[2].value,entry[2])
            self.assertGreater(sheet.row_dimensions[row[0].row].height,120)
            self.assertTrue(any(r[0].value and r[1].value is None for r in sheet.iter_rows(min_row=2)))
            for tab in book:
                with self.subTest(sheet=tab.title):
                    self.assertEqual(tab.freeze_panes,'C2')
                    self.assertEqual(tab.auto_filter.ref,tab.dimensions)
                    self.assertTrue(tab['A2'].font.bold)
                    self.assertTrue(tab['B2'].font.bold)
                    self.assertEqual(tab['A2'].fill.fgColor.theme,4)
                    self.assertEqual(tab['B2'].fill.fgColor.theme,8)
                    for cell in tab[2]:
                        self.assertEqual(cell.font.name,'微软雅黑')
                        self.assertTrue(cell.alignment.wrap_text)
                        self.assertEqual(cell.border.left.style,'thin')
            for tab,header in ((sheet,language_exchange._header('ja-JP')),
                               (next(tab for tab in book if tab.title.endswith('(en-US)')),writer.HEADER)):
                self.assertEqual([cell.value for cell in tab[1]],header)
                self.assertTrue(tab.column_dimensions['G'].hidden)
                self.assertTrue(tab.column_dimensions['H'].hidden)
                for col,field in enumerate(writer.HEADER_FIELDS[:6],1):
                    self.assertAlmostEqual(tab.column_dimensions[get_column_letter(col)].width,
                                           excel_format.preset()['columns'][field]['width'])
        finally:book.close()
        self.assertFalse(pairs.path().exists(),'Export must never save the active draft')
        english=store.read()
        result=client.post('/api/lexicon/import',json={'paths':[str(target)],'language':'en-US','fingerprint':english['fingerprint']})
        self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['sheets'],16)
        self.assertTrue(any(row[:2]==entry[:2] for row in pairs.table('ja-JP')['rows']))
        self.assertFalse(any(row[:2]==entry[:2] for row in pairs.table('ko')['rows']))
        self.assertEqual(store.read()['fingerprint'],english['fingerprint'])

    def _sample_exchange(self, invalid=False):
        from openpyxl import Workbook
        path=Path(self.tmp.name)/'exchange.xlsx'
        book=Workbook()
        english=book.active;english.title='英语 (en-US)'
        english.append(writer.HEADER);english.append(['交换专用名词','exchange example','','','','',1,'','term'])
        korean=book.create_sheet('韩语 (ko)')
        korean.append(['中文术语','错误标题' if invalid else '标准韩语','英文术语'])
        korean.append(['交换专用名词','교환 예제','exchange example'])
        french=book.create_sheet('法语 (fr-FR)')
        french.append(['中文术语','标准法语','英文术语'])
        french.append(['交换专用名词','exemple de transfert','exchange example'])
        book.save(path);book.close()
        return path

    def test_all_languages_json_preserves_missing_terms_and_applies_import(self):
        client=app.test_client()
        table=pairs.table('ko')
        table['rows'].append(['JSON 试验词','JSON 테스트','','','','','1','','term','','','',''])
        target=Path(self.tmp.name)/'all-languages.json'
        result=client.post('/api/lexicon/export',json={**table,'path':str(target),'all_languages':True,'destination_fingerprint':''})
        self.assertEqual(result.status_code,200,result.json)
        value=json.loads(target.read_text('utf-8'))
        self.assertEqual(value['format'],workbook_exchange.FORMAT)
        self.assertEqual({sheet['language'] for sheet in value['sheets']},{item['code'] for item in catalog.read()['languages']})
        self.assertFalse(pairs.path().exists())
        french=next(sheet for sheet in value['sheets'] if sheet['language']=='fr-FR')
        self.assertTrue(any(not row[1] for row in french['rows']))
        french['rows'].append(['JSON 试验词','exemple JSON',''])
        target.write_text(json.dumps(value,ensure_ascii=False),'utf-8')
        response=client.post('/api/lexicon/import',json={'paths':[str(target)],'fingerprint':store.read()['fingerprint'],'all_languages':True})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['sheets'],16)
        self.assertTrue(any(row[:2]==['JSON 试验词','JSON 테스트'] for row in pairs.table('ko')['rows']))
        self.assertTrue(any(item['terms'].get('fr-FR')=='exemple JSON' for item in catalog.lookup()['entries']))

    def test_current_language_scope_ignores_unselected_sheets_in_excel_and_json(self):
        client=app.test_client()
        english=store.read()
        french=Path(self.tmp.name)/'selected.json'
        french.write_text(json.dumps({'schema':1,'format':workbook_exchange.FORMAT,'sheets':[
            {'language':'ko','columns':['中文术语','标准韩语','英文术语'],'rows':[['范围测试词','범위 테스트','scope test']]},
            {'language':'en-US','columns':['格式错误的其他语种表'],'rows':[]},
        ]},ensure_ascii=False),'utf-8')
        for path in (self._sample_exchange(),french):
            table=pairs.table('ko')
            response=client.post('/api/lexicon/import',json={**table,'paths':[str(path)],'all_languages':False})
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['sheets'],1)
            self.assertEqual(store.read()['fingerprint'],english['fingerprint'])
            self.assertEqual(len(catalog.lookup()['entries']),1902)
        self.assertTrue(any(row[:2]==['范围测试词','범위 테스트'] for row in pairs.table('ko')['rows']))

    def test_import_named_sheets_merges_all_languages_and_refreshes_reference(self):
        client=app.test_client()
        path=self._sample_exchange()
        draft=pairs.table('zh-Hant-TW')
        draft['rows'].append(['独立草稿术语','獨立草稿術語','','','','','1','','term','','','',''])
        response=client.post('/api/lexicon/import',json={**draft,'paths':[str(path)]})
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(any(e['en']=='exchange example' for e in store.read()['entries']))
        self.assertTrue(any(row[:2]==['交换专用名词','교환 예제'] for row in pairs.table('ko')['rows']))
        self.assertTrue(any(row[:2]==['独立草稿术语','獨立草稿術語'] for row in pairs.table('zh-Hant-TW')['rows']))
        found=next(row for row in client.get('/api/lexicon/catalog').json['entries'] if row['terms'].get('fr-FR')=='exemple de transfert')
        self.assertEqual((found['terms']['zh-CN'],found['terms']['en-US']),('交换专用名词','exchange example'))
        self.assertFalse(any(row['terms'].get('fr-FR')=='exemple de transfert' for row in catalog.read()['entries']))
        before=(store.read()['fingerprint'],pairs.path().read_bytes())
        response=client.post('/api/lexicon/import',json={'paths':[str(path)],'fingerprint':before[0]})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual((store.read()['fingerprint'],pairs.path().read_bytes()),before)

    def test_bulk_import_into_shared_excel_preserves_custom_columns(self):
        from openpyxl import Workbook, load_workbook
        shared=Path(self.tmp.name)/'shared.xlsx'
        book=Workbook();book.active.append(['中文','英文','项目编号']);book.active.append(['既有术语','existing term','A-123'])
        book.save(shared);book.close()
        store.select(str(shared))
        client=app.test_client()
        table=client.get('/api/glossary/table').json
        table['rows'][0][2]='A-456'
        response=client.post('/api/lexicon/import',json={**table,'language':'en-US','paths':[str(self._sample_exchange())],'all_languages':True})
        self.assertEqual(response.status_code,200,response.json)
        adapted=load_workbook(shared,read_only=True)
        try:
            self.assertEqual(adapted.active['C1'].value,'项目编号')
            self.assertEqual(adapted.active['C2'].value,'A-456')
        finally:adapted.close()
        self.assertTrue(any(entry['en']=='exchange example' for entry in store.read()['entries']))
        self.assertTrue(any(row[:2]==['交换专用名词','교환 예제'] for row in pairs.table('ko')['rows']))

    def test_invalid_sheet_or_failed_file_replace_keeps_all_languages_intact(self):
        client=app.test_client()
        english=store.read();target=Path(english['path']).resolve()
        data={'paths':[str(self._sample_exchange(invalid=True))],'fingerprint':english['fingerprint']}
        self.assertEqual(client.post('/api/lexicon/import',json=data).status_code,400)
        self.assertEqual(store.fingerprint(target),english['fingerprint'])
        self.assertFalse(pairs.path().exists())
        data['paths']=[str(self._sample_exchange())]
        replace=workbook_exchange.os.replace
        def fail_primary(source,destination):
            if Path(destination).resolve()==target:raise PermissionError('test lock')
            return replace(source,destination)
        with patch.object(workbook_exchange.os,'replace',side_effect=fail_primary):
            with self.assertRaises(PermissionError):
                workbook_exchange.import_files(data['paths'],'en-US',data['fingerprint'],None,None)
        self.assertEqual(store.fingerprint(target),english['fingerprint'])
        self.assertFalse(pairs.path().exists())

if __name__=='__main__':unittest.main()
