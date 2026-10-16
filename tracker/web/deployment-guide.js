(()=>{
 function reveal(){const id=decodeURIComponent(location.hash.slice(1));const item=document.getElementById(id);if(item?.tagName==='DETAILS'){item.open=true;item.scrollIntoView({block:'start'});}}
 window.addEventListener('hashchange',reveal);reveal();
})();
