"""Observe actual requests without changing their prompts, results or retries."""
class RequestActivity:
    def __init__(self,client,activity):self.client,self.activity=client,activity
    def __getattr__(self,name):return getattr(self.client,name)
    def chat_json(self,*args,**kwargs):
        self.activity('等待模型响应')
        try:result=self.client.chat_json(*args,**kwargs)
        except Exception:
            self.activity('保留成果，准备重试');raise
        self.activity('校验模型返回内容')
        return result
