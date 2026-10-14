// A disclosure works with pointer, Enter/Space and Escape; no hover-only help.
(() => {
  for (const options of document.querySelectorAll('[data-translation-options]')) {
    const button=options.querySelector('.translation-help-button'),help=document.getElementById(button.getAttribute('aria-controls'));
    button.addEventListener('click',()=>{const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));help.hidden=!open});
    options.addEventListener('keydown',event=>{if(event.key==='Escape'&&!help.hidden){help.hidden=true;button.setAttribute('aria-expanded','false');button.focus();event.stopPropagation()}});
  }
})();
