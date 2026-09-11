from pathlib import Path

career_file = Path("release/career-pro.html")
html = career_file.read_text(encoding="utf-8")

# Keep the existing Career Pro hero exactly the same.
old_hero = (
    '<section class="hero"><b class="badge">CAREER PRO V2</b>'
    '<h1>Turn your resume into a stronger <span>application.</span></h1>'
    '<p>Upload your resume, match it to a real job, optimize the content, '
    'and create application-ready material without inventing experience.</p>'
    '</section>'
)

# Only add the three existing-theme buttons underneath the tagline.
new_hero = (
    '<section class="hero"><b class="badge">CAREER PRO V2</b>'
    '<h1>Turn your resume into a stronger <span>application.</span></h1>'
    '<p>Upload your resume, match it to a real job, optimize the content, '
    'and create application-ready material without inventing experience.</p>'
    '<div class="tabs" style="justify-content:center;flex-wrap:wrap">'
    '<button class="tab active" data-panel="opt">Resume Optimizer</button>'
    '<button class="tab" data-panel="letter">AI Cover Letter</button>'
    '<button class="tab" data-panel="summary">AI PDF Summarizer</button>'
    '</div></section>'
)

if old_hero not in html:
    raise RuntimeError("Original Career Pro hero was not found. No changes were made.")

html = html.replace(old_hero, new_hero, 1)

# Remove the old two-button row so buttons appear only under the tagline.
old_tabs = (
    '<div class="tabs">'
    '<button class="tab active" data-panel="opt">Resume Optimizer</button>'
    '<button class="tab" data-panel="letter">AI Cover Letter</button>'
    '</div>'
)

if old_tabs not in html:
    raise RuntimeError("Original Career Pro buttons were not found. No changes were made.")

html = html.replace(old_tabs, "", 1)

# Add the PDF Summarizer as another panel using the page's existing classes.
workspace_end = '</section>\n</section>\n</main>'

summary_panel = '''</section>
<section class="card panel" id="summary">
  <h2>AI PDF Summarizer</h2>
  <p class="muted">Upload a text-based PDF and get a clear overview, key points, important details and action items.</p>
  <div class="drop" id="summaryDrop">
    <b>Drop a PDF here or click to browse</b>
    <small>PDF only · up to 15 MB · up to 120 pages</small>
    <div class="uploadmsg" id="summaryUploadMessage"></div>
  </div>
  <input id="summaryFile" type="file" accept="application/pdf,.pdf" hidden>
  <select id="summaryDetail" aria-label="Summary detail">
    <option value="short">Short summary</option>
    <option value="detailed">Detailed summary</option>
  </select>
  <button class="btn" id="summaryButton" disabled>Summarize PDF</button>
  <div class="feature-note">Scanned or image-only PDFs are not supported yet. Use a text-based PDF or OCR the file first.</div>
  <div class="output" id="summaryOutput"></div>
</section>
</section>
</main>'''

if workspace_end not in html:
    raise RuntimeError("Career Pro workspace ending was not found. No changes were made.")

html = html.replace(workspace_end, summary_panel, 1)

# Keep the existing tab behavior, but hide resume/job inputs only for PDF Summarizer.
old_tab_script = (
    "document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{"
    "document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));"
    "b.classList.add('active');"
    "$(b.dataset.panel).classList.add('active')});"
)

new_tab_script = (
    "document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{"
    "document.querySelectorAll('.tab,.panel').forEach(x=>x.classList.remove('active'));"
    "b.classList.add('active');"
    "$(b.dataset.panel).classList.add('active');"
    "document.querySelector('.inputs').style.display="
    "b.dataset.panel==='summary'?'none':'grid'"
    "});"
)

if old_tab_script not in html:
    raise RuntimeError("Original tab behavior was not found. No changes were made.")

html = html.replace(old_tab_script, new_tab_script, 1)

# Add PDF Summarizer behavior. Existing optimizer and cover-letter code is untouched.
summary_script = r'''
const summaryDrop = $('summaryDrop');
const summaryFile = $('summaryFile');
const summaryButton = $('summaryButton');
let selectedSummaryPdf = null;
let lastSummaryText = '';

summaryDrop.onclick = () => summaryFile.click();

['dragenter', 'dragover'].forEach(eventName => {
  summaryDrop.addEventListener(eventName, event => {
    event.preventDefault();
    summaryDrop.classList.add('drag');
  });
});

['dragleave', 'drop'].forEach(eventName => {
  summaryDrop.addEventListener(eventName, event => {
    event.preventDefault();
    summaryDrop.classList.remove('drag');
  });
});

summaryDrop.addEventListener('drop', event => {
  const file = event.dataTransfer.files[0];
  if (file) selectSummaryPdf(file);
});

summaryFile.onchange = () => {
  if (summaryFile.files[0]) selectSummaryPdf(summaryFile.files[0]);
};

function selectSummaryPdf(file) {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    $('summaryUploadMessage').textContent = 'Choose a PDF file.';
    selectedSummaryPdf = null;
    summaryButton.disabled = true;
    return;
  }

  selectedSummaryPdf = file;
  $('summaryUploadMessage').textContent = 'Selected: ' + file.name;
  summaryButton.disabled = false;
}

function renderSummaryList(title, items) {
  if (!items || !items.length) return '';
  return '<div class="block"><h3>' + esc(title) + '</h3><ul>' +
    items.map(item => '<li>' + esc(item) + '</li>').join('') +
    '</ul></div>';
}

function buildSummaryText(summary, documentInfo) {
  const lines = [
    summary.title,
    '',
    summary.overview,
    '',
    'Key points:',
    ...(summary.key_points || []).map(item => '• ' + item)
  ];

  if (summary.important_details?.length) {
    lines.push('', 'Important details:', ...summary.important_details.map(item => '• ' + item));
  }

  if (summary.action_items?.length) {
    lines.push('', 'Action items:', ...summary.action_items.map(item => '• ' + item));
  }

  lines.push('', 'Source: ' + documentInfo.filename + ' · ' + documentInfo.page_count + ' pages');
  return lines.join('\n');
}

summaryButton.onclick = async function () {
  const output = $('summaryOutput');
  if (!selectedSummaryPdf) return;

  this.disabled = true;
  this.textContent = 'Summarizing…';
  $('summaryUploadMessage').textContent = 'Reading and summarizing ' + selectedSummaryPdf.name + '…';

  try {
    const form = new FormData();
    form.append('session_id', session);
    form.append('pdf', selectedSummaryPdf);
    form.append('detail', $('summaryDetail').value);

    const response = await fetch(API + '/api/career/pro/pdf-summary', {
      method: 'POST',
      body: form
    });

    const data = await response.json();
    if (!response.ok || !data.success) {
      throw new Error(data.error || 'PDF summary failed.');
    }

    const summary = data.summary;
    const documentInfo = data.document;
    lastSummaryText = buildSummaryText(summary, documentInfo);

    output.innerHTML =
      '<div class="block"><h3>' + esc(summary.title) + '</h3>' +
      '<div class="pre">' + esc(summary.overview) + '</div></div>' +
      renderSummaryList('Key points', summary.key_points) +
      renderSummaryList('Important details', summary.important_details) +
      renderSummaryList('Action items', summary.action_items) +
      '<div class="integrity">' + esc(summary.integrity_note || '') + '</div>' +
      '<div class="actions"><button class="btn secondary" id="copySummary">Copy Summary</button></div>';

    output.style.display = 'block';
    $('copySummary').onclick = () => navigator.clipboard.writeText(lastSummaryText);
    $('summaryUploadMessage').textContent = 'Summary ready.';
  } catch (error) {
    output.textContent = error.message;
    output.style.display = 'block';
    $('summaryUploadMessage').textContent = '';
  } finally {
    this.disabled = false;
    this.textContent = 'Summarize PDF';
  }
};
'''

html = html.replace('</script>', summary_script + '\n</script>', 1)

career_file.write_text(html, encoding="utf-8")
print("Career Pro buttons added without changing the existing theme.")
