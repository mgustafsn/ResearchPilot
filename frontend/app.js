const content = document.querySelector('#content');
const errorBox = document.querySelector('#error');
function showError(error) { errorBox.textContent = error.message; errorBox.hidden = false; }
async function api(path = '', options = {}) {
  const response = await fetch(`/api/projects${path}`, options);
  if (!response.ok) {
    const body = await response.json();
    throw new Error(Array.isArray(body.detail) ? body.detail.map(e => `${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ') : body.detail || 'Request failed');
  }
  return response.status === 204 ? null : response.json();
}
function element(tag, text, parent = content) {
  const el = document.createElement(tag); el.textContent = text; parent.append(el); return el;
}
function link(text, href, parent = content) {
  const el = element('a', text, parent); el.href = href; return el;
}
function form(project = {}) {
  element('h1', project.id ? 'Edit project' : 'Create a research project');
  const f = document.createElement('form');
  f.innerHTML = `<label for="title">Project title</label><input id="title" name="title" required maxlength="200">
    <label for="researchQuestion">Research question or topic</label><textarea id="researchQuestion" name="researchQuestion" required maxlength="5000"></textarea>
    <label for="keywords">Keywords <small>(optional, one per line)</small></label><textarea id="keywords" name="keywords"></textarea>
    <div class="row"><div><label for="yearFrom">From year <small>(optional)</small></label><input id="yearFrom" name="yearFrom" type="number" min="1" max="9999"></div>
    <div><label for="yearTo">To year <small>(optional)</small></label><input id="yearTo" name="yearTo" type="number" min="1" max="9999"></div>
    <div><label for="maxPaperCount">Paper limit <small>(optional)</small></label><input id="maxPaperCount" name="maxPaperCount" type="number" min="1" max="1000"></div></div>
    <p class="muted">Save your question and preferences for this project.</p><div class="actions"><button type="submit">Save project</button></div>`;
  content.append(f);
  for (const name of ['title', 'researchQuestion', 'yearFrom', 'yearTo', 'maxPaperCount']) f.elements[name].value = project[name] ?? '';
  f.elements.keywords.value = (project.keywords || []).join('\n');
  link('Cancel', project.id ? `/projects/${project.id}` : '/', f.querySelector('.actions'));
  f.addEventListener('submit', async event => {
    event.preventDefault(); errorBox.hidden = true;
    const data = {title: f.elements.title.value, researchQuestion: f.elements.researchQuestion.value,
      keywords: f.elements.keywords.value.split('\n').map(s => s.trim()).filter(Boolean)};
    for (const name of ['yearFrom', 'yearTo', 'maxPaperCount']) data[name] = f.elements[name].value === '' ? null : Number(f.elements[name].value);
    const button = f.querySelector('button'); button.disabled = true;
    try { const saved = await api(project.id ? `/${project.id}` : '', {method: project.id ? 'PUT' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)}); location.href = `/projects/${saved.id}`; }
    catch (error) { showError(error); button.disabled = false; }
  });
}
async function render() {
  const parts = location.pathname.split('/').filter(Boolean);
  if (!parts.length) {
    const projects = await api(); content.replaceChildren();
    element('h1', 'Your research projects');
    element('p', 'Keep your questions and research preferences in one place.').className = 'muted';
    link('New project', '/projects/new').className = 'button';
    if (!projects.length) element('p', 'No projects yet. Create your first research project.');
    for (const project of projects) {
      const card = element('div', ''); card.className = 'card';
      link(project.title, `/projects/${project.id}`, element('h2', '', card));
      element('p', project.researchQuestion, card);
      element('small', `Updated ${new Date(project.updatedAt).toLocaleString()}`, card);
    }
  } else if (parts[1] === 'new') { content.replaceChildren(); form(); }
  else {
    const project = await api(`/${parts[1]}`); content.replaceChildren();
    if (parts[2] === 'edit') { form(project); return; }
    element('h1', project.title);
    const article = element('article', '');
    element('h2', 'Research question', article); element('p', project.researchQuestion, article);
    element('p', `Keywords: ${project.keywords.join(', ') || 'None'}`, article);
    element('p', `Publication years: ${project.yearFrom ?? 'Any'} – ${project.yearTo ?? 'Any'}`, article);
    element('p', `Maximum papers: ${project.maxPaperCount ?? 'Not specified'}`, article);
    element('small', `Created ${new Date(project.createdAt).toLocaleString()}`, article);
    const actions = element('div', ''); actions.className = 'actions';
    link('Edit project', `/projects/${project.id}/edit`, actions).className = 'button';
    const remove = element('button', 'Delete project', actions); remove.className = 'danger';
    remove.addEventListener('click', async () => {
      if (!confirm(`Delete “${project.title}”? This cannot be undone.`)) return;
      remove.disabled = true;
      try { await api(`/${project.id}`, {method:'DELETE'}); location.href = '/'; }
      catch (error) { showError(error); remove.disabled = false; }
    });
  }
}
render().catch(error => { content.textContent = 'Unable to load this page.'; showError(error); });
