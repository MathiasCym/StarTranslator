"""Actual failure shapes: equivalent quantities, valid identity and failed-item repair."""
import json,sys,threading,unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from backend.text_languages import validate,translate_piece
from backend.multilingual_quality import LanguageReview,IncompleteLanguageReview,chinese_script
from backend.translation_retry import repaired_pages

class CoverageTests(unittest.TestCase):
    def test_document_validation_protects_links_and_does_not_reject_quantity_differences(self):
        from backend.multilingual_documents import content_validate

        source='A8 控制器的容差为30.00%，工作温度可达−20 °C。'
        target='A8 컨트롤러의 허용 오차는 30 퍼센트이며, 작동 온도는 마이너스 20 °C까지입니다.'
        content_validate(source,target,'zh-CN','ko')
        for changed in (target.replace('30 퍼센트','30'),target.replace('마이너스 ',''),
                        target.replace('30 퍼센트','31 퍼센트')):
            with self.subTest(changed=changed):
                content_validate(source,changed,'zh-CN','ko')
                with self.assertRaises(ValueError):validate(source,changed,'zh-CN','ko')
        content_validate(source,target.replace('A8','A 8'),'zh-CN','ko')
        with self.assertRaisesRegex(ValueError,'网址'):
            content_validate(source+' https://example.com/a',target+' https://example.com/b','zh-CN','ko')
        content_validate('GPU负责显示计算。','그래픽 처리 장치가 디스플레이 연산을 담당합니다.','zh-CN','ko')
        # Grammar need not produce comparable digit tokens on both sides.
        content_validate('至少预留3个座位。','좌석을 적어도 세 자리 남겨 주세요.','zh-CN','ko')
        content_validate('工作负荷约为50%。','부하는 절반 정도입니다.','zh-CN','ko')

    def test_localized_calendar_and_plan_counts_preserve_values(self):
        for dst,calendar,plan in [
            ('ja-JP','2025年5月9日','2021年の第14次五カ年計画'),
            ('ko','2025년 5월 9일','2021년 제14차 5개년 계획'),
            ('zh-Hant-TW','2025年5月9日','2021年《十四五規劃》'),
            ('en-US','May 9, 2025','2021 14th Five-Year Plan'),
        ]:
            with self.subTest(dst=dst):
                validate('2025.05.09',calendar,'zh-CN',dst)
                validate('2021年《“十四五”规划》',plan,'zh-CN',dst)
                with self.assertRaises(ValueError):
                    validate('2025.05.10',calendar,'zh-CN',dst)
                with self.assertRaises(ValueError):
                    validate('2021年《“十五五”规划》',plan,'zh-CN',dst)
        validate('为剧场设计的一套LED控制系统','劇場向けLED制御システム','zh-CN','ja-JP')
        validate('基于一个基础假设','ある基本的な前提に基づく','zh-CN','ja-JP')
        validate('实现从零到一的突破','ゼロからイチへの飛躍を実現','zh-CN','ja-JP')
        validate('实现从零到一的突破','ゼロから1への飛躍を実現','zh-CN','ja-JP')
        validate('成为升级首选','アップグレードの第一選択肢となった','zh-CN','ja-JP')
        validate('建成北京、上海双中心','北京と上海の2拠点を整備した','zh-CN','ja-JP')
        with self.assertRaises(ValueError):
            validate('建成北京、上海双中心','北京と上海の3拠点を整備した','zh-CN','ja-JP')
        with self.assertRaises(ValueError):
            validate('为剧场设计的一套LED控制系统','劇場向けの複数のLED制御システム','zh-CN','ja-JP')
        with self.assertRaises(ValueError):
            validate('成为升级首选','アップグレードの第二選択肢となった','zh-CN','ja-JP')
        source='今天的工作全部完成，明天可以正常使用。'
        with self.assertRaisesRegex(ValueError,'仍与原文相同'):
            validate(source,source,'zh-CN','ja-JP')

    def test_japanese_rejects_copied_simplified_text_even_with_old_certificate(self):
        source='新城LED电影公园'
        with self.assertRaisesRegex(ValueError,'中文简化字'):
            validate(source,source,'zh-CN','ja-JP',allow_identical=True)
        validate(source,'新城LED映画公園','zh-CN','ja-JP')
        validate('星辰电器推出新版','セイシン電器（星辰电器）が新版を発表','zh-CN','ja-JP')
        validate('使用率','使用率','zh-CN','ja-JP')

    def test_word_fragments_keep_calendar_precision_and_explicit_counts(self):
        for source,correct,incorrect in [
            ('。8月22日票价为41美元','。8월 22일 요금은 41달러','。8월 21일 요금은 41달러'),
            ('2026年8月21日至22日','2026년 8월 21일부터 22일까지','2026년 8월 21일부터 23일까지'),
            ('2026年8月21日至22日','2026년 8월 21일~22일','2026년 8월 21일'),
            ('2026年8月21日至22日','2026년 8월 21~22일','2026년 8월 21~23일'),
            ('三层观看区','3층 관람 구역','2층 관람 구역'),
            ('双人位','2인석','3인석'),
            ('；单次到店','; 한 번 방문','; 두 번 방문'),
            ('现场三维环境','현장 3차원 환경','현장 2차원 환경'),
            ('两个球门后和两条蓝线处','두 골대 뒤와 두 블루라인 지점','세 골대 뒤와 두 블루라인 지점'),
            ('复用同一套设备','동일한 장비를 재사용','동일한 장비 2세트를 재사용'),
        ]:
            with self.subTest(source=source,correct=correct):
                validate(source,correct,'zh-CN','ko')
                with self.assertRaisesRegex(ValueError,'数字或日期'):
                    validate(source,incorrect,'zh-CN','ko')


    def test_traditional_rejects_copied_simplified_text_but_keeps_shared_characters(self):
        source='控制器连接后启动显示屏。'
        with self.assertRaisesRegex(ValueError,'中文简化字'):
            validate(source,'控制器連接後啟動显示屏。','zh-CN','zh-Hant-TW',allow_identical=True)
        validate(source,'控制器連接後啟動顯示螢幕。','zh-CN','zh-Hant-TW')
        validate('使用率','使用率','zh-CN','zh-Hant-TW',allow_identical=True)

    def test_completed_page_refills_worker_while_earlier_page_is_slow(self):
        from backend.document_parallel import ordered_groups
        later_page_started=threading.Event()
        def compute(page):
            if page==0 and not later_page_started.wait(3):
                raise AssertionError('Free worker remained idle behind an earlier page')
            if page==2:later_page_started.set()
            return page
        self.assertEqual(list(ordered_groups(range(3),compute,2,threading.Event())),[0,1,2])


    def test_script_repair_reuses_candidate_without_an_independent_review(self):
        source='新城LED电影公园'
        translated='新城LED映画公園'
        class Model:
            def __init__(self):self.calls=[]
            def chat_json(self,prompt,**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0]
                self.calls.append(payload)
                if '待译原文' in payload:
                    return {'translation':translated if '上次译文（只修正仍未翻译的词）' in payload else source}
                return {'ok':True,'issues':[]}
        model=Model()
        self.assertEqual(translate_piece(model,source,None,'zh-CN','ja-JP',threading.Event(),terminology=False),translated)
        self.assertEqual(len(model.calls),2)
        self.assertEqual(model.calls[1]['上次译文（只修正仍未翻译的词）'],source)

    def test_ordinal_ranks_are_equivalent_but_changed_rank_is_rejected(self):
        for src,dst,source,target in [
            ('zh-CN','ko','中国银幕数量位居世界第一','중국 스크린 수는 세계 1위입니다'),
            ('zh-CN','ja-JP','位居世界第一','世界一です'),
            ('zh-CN','zh-Hant-TW','世界第一','世界第一'),
            ('zh-CN','en-US','世界第一','first in the world'),
            ('en-US','ko','the third display','세 번째 디스플레이'),
        ]:
            with self.subTest(src=src,dst=dst):validate(source,target,src,dst,allow_identical=True)
        for target in ('세계 2위입니다','second in the world','世界第二'):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):validate('世界第一',target,'zh-CN','ko')
        validate('首先检查连接','First check the connection','zh-CN','en-US')
        validate('世界一流技术','world-class technology','zh-CN','en-US')

    def test_korean_document_titles_are_translated_and_original_name_glosses_allowed(self):
        source='2021年《“十四五”规划》'
        validate(source,'2021년 제14차 5개년 계획','zh-CN','ko')
        with self.assertRaisesRegex(ValueError,'未译汉字'):
            validate(source,'2021년 《“十四五”规划》','zh-CN','ko')
        with self.assertRaises(ValueError):
            validate(source,'2021년 제15차 5개년 계획','zh-CN','ko')
        validate('中影完成制版','중국영화(中影)가 마스터링을 완료했다','zh-CN','ko')
        with self.assertRaisesRegex(ValueError,'未译汉字（场馆）'):
            validate('中影的新场馆开放','중국영화(中影)의 새 场馆이 문을 열었다','zh-CN','ko')
        for before,after in [
            ('투과음 구조를 설명한다','투과음(透声) 구조를 설명한다'),
            ('투과음 구조를 설명한다','透声 구조를 설명한다'),
            ('로프(洛普)의 자료','로프(洛普)의 장비(设备) 자료'),
        ]:
            with self.subTest(after=after),self.assertRaisesRegex(ValueError,'未译汉字'):
                validate(before,after,'ko','ko')
        validate('로프(洛普)의 자료','로프(洛普)의 공개 자료','ko','ko')

    def test_cross_language_validation_rejects_short_remaining_words(self):
        for source,target,src,dst in (
            ('照明を消す。','조명을 끄세요. テスト','ja-JP','ko'),
            ('비상 조명을 확인하세요.','非常灯を点検してください。 비상','ko','ja-JP'),
            ('照明を消す。','關閉照明。 テスト','ja-JP','zh-Hant-TW'),
        ):
            with self.subTest(target=dst),self.assertRaisesRegex(ValueError,'其他语种文字（(?:テスト|비상)）'):
                validate(source,target,src,dst)

    def test_japanese_date_ranges_keep_both_endpoints_in_other_languages(self):
        source='2026年8月21日から22日まで'
        for dst,target,wrong in (
            ('ko','2026년 8월 21일부터 22일까지','2026년 8월 21일부터 23일까지'),
            ('zh-Hant-TW','2026年8月21日至22日','2026年8月21日'),
            ('en-US','August 21 to 22, 2026','August 21 to 23, 2026'),
        ):
            with self.subTest(target=dst):
                validate(source,target,'ja-JP',dst)
                with self.assertRaisesRegex(ValueError,'数字或日期'):
                    validate(source,wrong,'ja-JP',dst)
        validate('8月21日から22日まで','8월 21일부터 22일까지','ja-JP','ko')

    def test_technical_counts_and_calendar_eras_allow_equivalent_language(self):
        cases=(
            ('ja-JP','en-US','二次利用の条件','Conditions for reuse','Conditions for 2 reuse cases'),
            ('ja-JP','en-US','全4編の資料','The four volumes','The five volumes'),
            ('ja-JP','en-US','3種類を選択する','Choose three formats.','Choose two formats.'),
            ('ja-JP','en-US','一つ以上のデータを公開する','Publish at least one dataset.','Publish at least two datasets.'),
            ('ja-JP','en-US','1つでも公開してください。','Please publish even one.','Please publish even two.'),
            ('ja-JP','en-US','令和3年6月15日改定','Revised on June 15, 2021','Revised on June 15, 2022'),
            ('zh-Hant-TW','en-US','民國96年5月18日發行','Issued on May 18, 2007','Issued on May 18, 2008'),
            ('zh-Hant-TW','en-US','行政院96年5月18日發行','Issued by the Executive Yuan on May 18, 2007','Issued by the Executive Yuan on May 18, 2008'),
            ('zh-Hant-TW','en-US','行政院96年5月18日發行','Issued on May 18, 2007 (ROC year 96)','Issued on May 18, 2007 (ROC year 97)'),
            ('zh-Hant-TW','en-US','98年政府機關演練評審辦法規定','The 2009 government agency exercise review rules state','The 1998 government agency exercise review rules state'),
            ('ja-JP','en-US','平成29年5月30日改定','Revised on May 30, Heisei 29 [2017]','Revised on May 30, Heisei 29 [2018]'),
            ('zh-Hant-TW','en-US','電子郵件跟蹤(一、二)','Email tracking (1 and 2)','Email tracking (1 and 3)'),
            ('en-US','ja-JP','Two transmissions overlap by one bit.','2回の送信が1ビット重なる。','3回の送信が1ビット重なる。'),
            ('en-US','ja-JP','1 transition per bit, but twice as much bandwidth','1ビットあたり1回遷移するが、帯域幅は2倍必要。','1ビットあたり1回遷移するが、帯域幅は3倍必要。'),
            ('en-US','zh-Hant-TW','1 transition per bit, but twice as much bandwidth','每 bit 1 次轉換，但頻寬加倍','每 bit 1 次轉換，但頻寬為三倍'),
            ('en-US','zh-Hant-TW','Transmit over one pair of wires.','用一對導線傳送。','用兩對導線傳送。'),
            ('en-US','ko','1 transition per bit','비트당 전이 1회','2 비트당 전이 1회'),
            ('en-US','ja-JP','A single frame lasts one slot.','1フレームは1スロット続く。','1フレームは2スロット続く。'),
            ('en-US','ja-JP','Transmit over one pair of wires.','1対の導線で送信する。','2対の導線で送信する。'),
            ('en-US','ja-JP','10 years after the 1st specification','最初の仕様から10年後','最初の仕様から11年後'),
            ('en-US','ko','A long run of ones or zeros makes clock recovery difficult.','1이나 0이 길게 이어지면 클록 복구가 어렵다.','1이나 2가 길게 이어지면 클록 복구가 어렵다.'),
        )
        for src,dst,source,target,wrong in cases:
            with self.subTest(source=source):
                validate(source,target,src,dst)
                with self.assertRaisesRegex(ValueError,'数字或日期'):
                    validate(source,wrong,src,dst)

    def test_indefinite_articles_and_commands_in_mixed_language_documents(self):
        from backend.multilingual_documents import content_validate
        from backend.text_integrity import command_literal

        validate('A method that guarantees transitions','一種能保證轉換的方法','en-US','zh-Hant-TW')
        validate('A signal from one transmitter reaches another.','來自一個發射器的訊號抵達另一個發射器。','en-US','zh-Hant-TW')
        validate('一個使用者開啟一個登入頁面','A user opens a login page','zh-Hant-TW','en-US')
        with self.assertRaisesRegex(ValueError,'数字或日期'):
            validate('一個使用者開啟兩個登入頁面','A user opens a login page','zh-Hant-TW','en-US')
        for command in ('# traceroute -i eth0','site:example.org password inurl:help'):
            self.assertTrue(command_literal(command))
            content_validate(command,command,'zh-Hant-TW','en-US')
            with self.assertRaisesRegex(ValueError,'必须原样保留'):
                content_validate(command,command+' extra','zh-Hant-TW','en-US')
        self.assertFalse(command_literal('翻譯說明請參考 site:example.org'))

    def test_numeric_ranges_and_pixel_classifiers_across_document_languages(self):
        source='当比例超过30%时，电容可达15-30pF，扩散半径约为3-5个像素间距。'
        cases=(
            ('ko','비율이 30%를 넘으면 커패시턴스는 15 - 30 pF에 이르며, 확산 반경은 약 3~5개의 픽셀 피치입니다.'),
            ('ja-JP','比率が30%を超えると、静電容量は15 - 30 pFに達し、拡散半径は約3～5個のピクセルピッチになる。'),
            ('zh-Hant-TW','當比例超過30%時，電容可達15 - 30 pF，擴散半徑約為3～5個畫素間距。'),
            ('en-US','Above 30%, capacitance can reach 15 - 30 pF and the spread radius is about 3–5 pixel pitches.'),
        )
        for target_language,target in cases:
            with self.subTest(language=target_language):
                validate(source,target,'zh-CN',target_language)
                with self.assertRaisesRegex(ValueError,'正负号'):
                    validate(source,target.replace('15 - 30','−15 to 30'),'zh-CN',target_language)
        with self.assertRaisesRegex(ValueError,'数值单位'):
            validate(source,cases[0][1].replace('픽셀 피치','밀리미터'),'zh-CN','ko')

    def test_translation_preserves_uri_and_allows_localized_brackets(self):
        address='https://example.com/model(A)?v=2'
        source=f'資料の出典（{address}）'
        validate(source,f'Source ({address})','ja-JP','en-US')
        with self.assertRaisesRegex(ValueError,'改变了网址'):
            validate(source,f'Source ({address.replace("v=2","v=3")})','ja-JP','en-US')

    def test_bibliographic_product_name_requires_its_own_review_proof(self):
        source='[8] EXAMPLE TECHNOLOGY. CX Engine[EB/OL]. [2026-08-24].'
        for dst in ('ko','ja-JP','zh-Hant-TW','zh-CN'):
            with self.subTest(target=dst):
                quality=LanguageReview('en-US',dst)
                self.assertTrue(quality.review_identical_formula(source,source))
                self.assertIsNone(quality.proof(source,source))
                with self.assertRaises(ValueError):
                    validate(source,source,'en-US',dst)
                quality.validate_review(source,source,{'ok':True,'unchanged_source_spans':[
                    {'text':source,'target_language':dst,'valid':True,'reason':'Official product name CX Engine.'}
                ]})
                self.assertIsNotNone(quality.proof(source,source))
                validate(source,source,'en-US',dst,allow_identical=True)
                prose='[23] EXAMPLE HELP CENTER. What ticket options are available?[EB/OL]. [2026-08-24].'
                self.assertFalse(quality.review_identical_formula(prose,prose))
                with self.assertRaises(ValueError):
                    validate(prose,prose,'en-US',dst,allow_identical=True)

    def test_exact_scaled_quantities_grouping_counters_and_dimensions(self):
        validate('21.4万块，市场体量庞大','21만 4천 개, 시장 규모가 방대하다','zh-CN','ko')
        validate('亮度≥300尼特，支持4K 120Hz','밝기 ≥ 300니트, 4K 120Hz 지원','zh-CN','ko')
        validate('2024 六部委方案','2024 6개 부처 방안','zh-CN','ko')
        with self.assertRaises(ValueError):validate('2024 六部委方案','2024 5개 부처 방안','zh-CN','ko')
        validate('保证每一块LED屏幕显示准确','모든 LED 화면의 정확한 표시를 보장합니다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('保证每两块LED屏幕显示准确','모든 LED 화면의 정확한 표시를 보장합니다','zh-CN','ko')
        validate('基于一个基础假设','기본 가정에 근거합니다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('基于两个基础假设','기본 가정에 근거합니다','zh-CN','ko')
        validate('实现从零到一的突破','0에서 1로의 돌파구를 마련했다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('实现从零到一的突破','0에서 2로의 돌파구를 마련했다','zh-CN','ko')
        with self.assertRaises(ValueError):validate('亮度≥300尼特','밝기 ≥ 300밀리미터','zh-CN','ko')
        with self.assertRaises(ValueError):validate('21.4万块','21만 5천 개','zh-CN','ko')
        with self.assertRaises(ValueError):validate('21.4万块','21만, 4천 개','zh-CN','ko')
        validate('为影院打造的一套LED控制系统','영화관용 LED 제어 시스템','zh-CN','ko')
        with self.assertRaises(ValueError):validate('为影院打造的两套LED控制系统','영화관용 LED 제어 시스템','zh-CN','ko')
        with self.assertRaises(ValueError):validate('为影院打造的一套LED控制系统','영화관용 여러 LED 시스템들','zh-CN','ko')
        validate('130万像素','130만 화소','zh-CN','ko')
        validate('130만 화소','1,300,000 pixels','ko','en-US')
        with self.assertRaises(ValueError):validate('130万像素','13만 화소','zh-CN','ko')
        with self.assertRaises(ValueError):validate('130万像素','130만 밀리미터','zh-CN','ko')
        for source,target in [('带载\v130万像素','帶載\v130萬像素'),('130万像素','1,300,000畫素'),
                ('1.3 million pixels','130萬個像素'),('650,000 pixels','650000個像素'),
                ('500mm*500mm','500×500公厘'),('60 Hz','60赫茲')]:
            with self.subTest(source=source,target=target):validate(source,target,'en-US','zh-Hant-TW')
        for source,target in [('130万像素','13萬像素'),('650,000 pixels','650個像素'),
                ('500mm*500mm','500×500公分'),('130万像素','130萬公厘'),('60 Hz','60')]:
            with self.subTest(source=source,target=target):
                with self.assertRaises(ValueError):validate(source,target,'en-US','zh-Hant-TW')

    def test_correct_shared_formula_does_not_require_a_language_certificate(self):
        source='1 Gbps(109) × 使用率';q=LanguageReview('zh-CN','zh-Hant-TW')
        class Model:
            def __init__(self,cert):self.cert=cert;self.calls=[]
            def chat_json(inner,prompt,system='',**options):
                payload=json.JSONDecoder().raw_decode(prompt)[0];inner.calls.append((payload,system))
                if '待译原文' in payload:return {'translation':source}
                answer={'ok':True,'issues':[]}
                if inner.cert:answer['unchanged_source_spans']=[{'text':s,'target_language':'zh-Hant-TW','valid':True,'reason':'共用字形，公式與臺灣用語均正確。'} for s in q.candidates(source,source)]
                return answer
        model=Model(True);result=translate_piece(model,source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=q,terminology=False)
        self.assertEqual(result,source);self.assertEqual(len(model.calls),1)
        wide='1 Gbps（109） × 使用率'
        q=LanguageReview('zh-CN','zh-Hant-TW')
        self.assertTrue(q.review_identical_formula(source,wide));self.assertIn(wide,q.candidates(source,wide))
        q.validate_review(source,wide,{'ok':True,'issues':[],'unchanged_source_spans':[{'text':wide,'target_language':'zh-Hant-TW','valid':True,'reason':'公式同文；全形括號只屬排版差異。'}]})
        validate(source,wide,'zh-CN','zh-Hant-TW',allow_identical=bool(q.proof(source,wide)))
        self.assertEqual(translate_piece(Model(False),source,None,'zh-CN','zh-Hant-TW',threading.Event(),quality=LanguageReview('zh-CN','zh-Hant-TW'),terminology=False),source)

    def test_script_inventory_and_untranslated_clauses_keep_protected_literals(self):
        self.assertEqual(chinese_script('带载','zh-Hant-TW'),'帶載')
        q=LanguageReview('zh-CN','zh-Hant-TW')
        self.assertIn('带載',q.candidates('带载','带載'))
        with self.assertRaises(IncompleteLanguageReview):q.validate_review('带载','带載',{'ok':True,'issues':[]})
        for dst,target in [('zh-CN','正文。The display supports the controller.'),('zh-Hant-TW','正文。The display supports the controller.'),
                           ('ja-JP','本文です。The display supports the controller.'),('ko','본문입니다. The display supports the controller.')]:
            with self.subTest(dst=dst):
                with self.assertRaisesRegex(ValueError,'英文句子'):validate('The display supports the controller.',target,'en-US',dst)
        validate('`The display supports the controller.` 說明','`The display supports the controller.` 说明','zh-Hant-TW','zh-CN')

    def test_equivalent_formula_survives_document_style_mapping(self):
        from backend.multilingual_documents import mapped
        source='1 Gbps(109) × 使用率';target='1 Gbps（109） × 使用率'
        groups=[{'id':0,'text':'1 Gbps(10','key':()}, {'id':1,'text':'9','key':()}, {'id':2,'text':') × 使用率','key':()}]
        runs=[{'id':0,'text':'1 Gbps（10'}, {'id':1,'text':'9'}, {'id':2,'text':'） × 使用率'}]
        q=LanguageReview('zh-CN','zh-Hant-TW')
        class Model:
            def chat_json(self,prompt,**options):
                payload=json.loads(prompt)
                if '待译原文' in payload:return {'translation':target}
                if '原文' in payload:return {'ok':True,'issues':[],'unchanged_source_spans':[
                    {'text':s,'target_language':'zh-Hant-TW','valid':True,'reason':'公式共用字，括號排版等價。'} for s in q.candidates(source,target)]}
                if '译文样式片段' in payload:return {'ok':True,'issues':[]}
                return {'runs':runs}
        result=mapped(Model(),source,groups,{},'zh-CN','zh-Hant-TW',threading.Event(),'','faithful',quality=q)
        self.assertEqual(result,runs)

    def test_repair_is_bounded_and_only_failed_content_is_repeated(self):
        calls=Counter();items=[SimpleNamespace(id=str(i),file_path='fixture.pptx',slide=i,locator=str(i)) for i in range(3)]
        retried=[]
        def compute(item,repair_error=None):
            calls[item.id]+=1
            error=ValueError('original failure evidence') if item.id=='2' or item.id=='1' and repair_error is None else None
            if repair_error is not None:self.assertEqual(repair_error,'original failure evidence')
            return item,[] if error is None else None,[],error
        results=list(repaired_pages(items,compute,3,threading.Event(),lambda item:item,on_retry=lambda item,error:retried.append(item.id)))
        self.assertEqual(calls,{'0':1,'1':2,'2':2});self.assertEqual(len(results),3)
        self.assertEqual(len([r for r in results if r[3] is not None]),1);self.assertCountEqual(retried,['1','2'])



if __name__=='__main__':unittest.main()
