// HTML-only pagination adapter. The source DOCX and its cells are never edited.
function starWordAvailableHeight(page,body,fallback){
  const css=getComputedStyle(page),paper=parseFloat(css.minHeight);
  if(!paper)return fallback;
  const scale=page.getBoundingClientRect().width/page.offsetWidth||1;
  const top=(body.getBoundingClientRect().top-page.getBoundingClientRect().top)/scale;
  return Math.min(fallback,paper-top-(parseFloat(css.paddingBottom)||0))-3;
}
function starWordTableCanSplit(body){
  const visible=[...body.children].filter(n=>n.offsetHeight>0);
  if(visible.length!==1)return false;
  if(visible[0].tagName==='P')return visible[0].textContent.length>500;
  if(visible[0].tagName!=='TABLE')return false;
  const table=visible[0];
  if(table.dataset.starSplitStuck==='1')return false;
  const rows=[...table.rows].filter(row=>row.closest('table')===table);
  if(rows.filter(row=>row.dataset.tblHeader!=='1').length>1)return true;
  return rows.some(row=>
    getComputedStyle(row).breakInside!=='avoid'&&[...row.cells].every(c=>c.rowSpan===1)&&
    [...row.cells].some(c=>c.children.length>1||c.textContent.length>500));
}
function starSplitWordParagraph(block,body,available){
  if(!block||block.tagName!=='P'||block.querySelector('img,svg,table'))return null;
  const scale=body.getBoundingClientRect().width/body.offsetWidth||1;
  const limit=body.getBoundingClientRect().top+available*scale-4*scale;
  const walker=document.createTreeWalker(block,NodeFilter.SHOW_TEXT),nodes=[];
  while(walker.nextNode())nodes.push(walker.currentNode);
  const text=nodes.map(n=>n.data).join('');
  const point=offset=>{for(const n of nodes){if(offset<=n.length)return [n,offset];offset-=n.length;}return [block,block.childNodes.length];};
  let lo=0,hi=text.length;
  while(lo<hi){const mid=Math.ceil((lo+hi)/2),range=document.createRange();
    range.selectNodeContents(block);range.setEnd(...point(mid));
    if(range.getBoundingClientRect().bottom<=limit)lo=mid;else hi=mid-1;
  }
  if(lo<=0||lo>=text.length)return null;
  let boundary=lo;
  if(/[A-Za-z0-9]/.test(text[lo-1]+text[lo])){
    while(boundary>0&&!/\s/.test(text[boundary-1]))boundary--;
    // PDF citations/URLs can have no whitespace anywhere. A visual fragment
    // may end inside that long token; the original characters stay untouched.
    if(!boundary)boundary=lo;
  }
  if(!boundary||limit-block.getBoundingClientRect().top<32*scale)return null;
  const tail=block.cloneNode(false);tail.removeAttribute('id');
  const range=document.createRange();range.selectNodeContents(block);range.setStart(...point(boundary));
  tail.appendChild(range.extractContents());tail.style.marginTop='0';
  tail.style.breakBefore='auto';tail.style.pageBreakBefore='auto';
  block.parentNode.insertBefore(tail,block.nextSibling);return tail;
}
function starSplitWordTable(table, body, available, depth=0) {
  if(depth>4)return null;
  const rows=[...table.rows].filter(r=>r.closest('table')===table);
  const scale=body.getBoundingClientRect().width/body.offsetWidth||1;
  // AutoFit decides widths against the COMPLETE table. Lock that measured
  // result before fragments lose different rows/min-content constraints.
  if(!table.dataset.starGridLocked){
    const cols=[...table.querySelectorAll(':scope>colgroup>col')];
    const widths=cols.map(c=>c.getBoundingClientRect().width/scale);
    if(cols.length&&widths.every(w=>w>0)){
      table.style.width=table.getBoundingClientRect().width/scale+'px';
      table.style.tableLayout='fixed';cols.forEach((c,i)=>c.style.width=widths[i]+'px');
      table.dataset.starGridLocked='1';
    }
  }
  const limit=body.getBoundingClientRect().top+available*scale;
  let cut=rows.findIndex(r=>r.getBoundingClientRect().bottom>limit+2*scale);
  if(cut<0)return null;
  // A vertical merge must stay attached to its owner. Ordinary row boundaries
  // may not discard the owner cell or shift subsequent cells into its column.
  let crossing=true;
  while(crossing){crossing=false;for(let i=0;i<cut;i++){
    if([...rows[i].cells].some(c=>i+c.rowSpan>cut)){cut=i;crossing=true;break;}
  }}
  const row=rows[cut], cells=[...row.cells];
  const splittable=getComputedStyle(row).breakInside!=='avoid'&&
    cells.every(c=>c.rowSpan===1)&&!rows.slice(0,cut).some((r,i)=>[...r.cells].some(c=>i+c.rowSpan>cut));
  // A long table body often lives in ONE cell, with many paragraphs and even
  // another table inside it. Moving that whole row creates large empty pages.
  if(splittable&&limit-row.getBoundingClientRect().top>45*scale){
    const plans=cells.map(cell=>{
      const blocks=[...cell.children];
      let at=blocks.findIndex(b=>b.getBoundingClientRect().bottom>limit-3*scale);
      if(at<0)return {cell,blocks,at:blocks.length};
      if(blocks[at].tagName==='TABLE'){
        const next=starSplitWordTable(blocks[at],body,available-3,depth+1);
        if(next){blocks.splice(at+1,0,next);at++;}
      }
      const block=blocks[at];
      // Split an overlong plain paragraph at a measured line/word boundary.
      // Range keeps inline emphasis and text order; it never rewrites text.
      let split=0;
      if(block&&/^(P|DIV|H[1-6])$/.test(block.tagName)&&!block.querySelector('img,svg,table')){
        const walker=document.createTreeWalker(block,NodeFilter.SHOW_TEXT),nodes=[];
        while(walker.nextNode())nodes.push(walker.currentNode);
        const text=nodes.map(n=>n.data).join('');
        const point=offset=>{for(const n of nodes){if(offset<=n.length)return [n,offset];offset-=n.length;}return [block,block.childNodes.length];};
        let lo=0,hi=text.length;
        while(lo<hi){const mid=Math.ceil((lo+hi)/2),end=point(mid),range=document.createRange();
          range.selectNodeContents(block);range.setEnd(...end);
          if(range.getBoundingClientRect().bottom<=limit-3*scale)lo=mid;else hi=mid-1;
        }
        if(lo>0&&lo<text.length){
          let boundary=lo;
          if(/[A-Za-z0-9]/.test(text[lo-1]+text[lo])){
            while(boundary>0&&!/\s/.test(text[boundary-1]))boundary--;
          }
          const line=parseFloat(getComputedStyle(block).lineHeight)||16;
          if(boundary>0&&limit-block.getBoundingClientRect().top>=line*scale*2)split=boundary;
        }
        if(split)return {cell,blocks,at,split,point};
      }
      return {cell,blocks,at};
    });
    if(plans.some(p=>p.at>0||p.split)&&plans.some(p=>p.at<p.blocks.length)){
      const continuation=row.cloneNode(false);continuation.removeAttribute('id');
      continuation.style.height='auto';continuation.style.minHeight='0';
      row.style.height='auto';row.style.minHeight='0';
      for(const p of plans){
        const next=p.cell.cloneNode(false);next.removeAttribute('id');next.style.verticalAlign='top';
        if(p.split){
          const block=p.blocks[p.at],tail=block.cloneNode(false);tail.removeAttribute('id');
          const range=document.createRange();range.selectNodeContents(block);range.setStart(...p.point(p.split));
          tail.appendChild(range.extractContents());tail.style.marginTop='0';next.appendChild(tail);
          p.at++;
        }
        p.blocks.slice(p.at).forEach(b=>next.appendChild(b));continuation.appendChild(next);
      }
      row.parentNode.insertBefore(continuation,row.nextSibling);rows.splice(cut+1,0,continuation);cut++;
    }
  }
  if(cut<=0){table.dataset.starSplitStuck='1';return null;}
  const continuation=table.cloneNode(false);continuation.removeAttribute('id');
  // The compiler's original row splitter drops colgroup, changing every width.
  [...table.children].filter(n=>n.tagName==='COLGROUP').forEach(n=>continuation.appendChild(n.cloneNode(true)));
  const target=document.createElement('tbody');continuation.appendChild(target);
  rows.filter((r,i)=>i<cut&&r.dataset.tblHeader==='1').forEach(r=>target.appendChild(r.cloneNode(true)));
  rows.slice(cut).forEach(r=>target.appendChild(r));
  table.parentNode.insertBefore(continuation,table.nextSibling);
  return continuation;
}
