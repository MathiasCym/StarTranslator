const http=require('node:http'),fs=require('node:fs'),path=require('node:path')
const site=path.join(__dirname,'dist')
const types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.json':'application/json; charset=utf-8'}
const server=http.createServer((req,res)=>{
  if (!['GET','HEAD'].includes(req.method)) { res.writeHead(405);res.end();return }
  let route;try { route=decodeURIComponent(new URL(req.url,'http://localhost').pathname) } catch { res.writeHead(400);res.end();return }
  const file=path.resolve(site,'.'+(route==='/'?'/index.html':route)),type=types[path.extname(file)]
  if(!file.startsWith(site+path.sep)||!type||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end('Not found');return}
  const headers={'Content-Type':type,'Content-Length':fs.statSync(file).size}
  res.writeHead(200,headers);if(req.method==='HEAD')res.end();else fs.createReadStream(file).pipe(res)
})
const port=Number(process.argv[2]||0)
if(!Number.isInteger(port)||port<0||port>65535)throw new Error('Invalid preview port')
server.listen(port,'127.0.0.1',()=>console.log('Local: http://127.0.0.1:'+server.address().port+'/'))
