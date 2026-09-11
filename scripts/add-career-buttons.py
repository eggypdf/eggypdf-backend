from pathlib import Path

career_file = Path("release/career-pro.html")
compress_file = Path("release/compress.html")

career_html = career_file.read_text(encoding="utf-8")
compress_html = compress_file.read_text(encoding="utf-8")

# -----------------------------------------------------------------------------
# Career Pro: keep the existing yellow/white theme and only add functionality.
# -----------------------------------------------------------------------------

old_hero = (
    '<section class="hero"><b class="badge">CAREER PRO V2</b>'
    '<h1>Turn your resume into a stronger <span>application.</span></h1>'
    '<p>Upload your resume, match it to a real job, optimize the content, '
    'and create application-ready material without inventing experience.</p>'
    '</section>'
)

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

if old_hero not in career_html:
    raise RuntimeError("Original Career Pro hero was not found.")

career_html = career_html.replace(old_hero, new_hero, 1)

old_tabs = (
    '<div class="tabs">'
    '<button class="tab active" data-panel="opt">Resume Optimizer</button>'
    '<button class="tab" data-panel="letter">AI Cover Letter</button>'
    '</div>'
)

if old_tabs not in career_html:
    raise RuntimeError("Original Career Pro tab row was not found.")

career_html = career_html.replace(old_tabs, "", 1)

# Highlight used only when an uploaded resume is over the 8 MB limit.
old_upload_style = '.uploadmsg{font-size:11.5px;margin-top:7px;color:#166534}'
new_upload_style = (
    old_upload_style
    + '.uploadmsg.warnsize{color:#9a3412;background:#fff7ed;'
      'border:1px solid #fed7aa;border-radius:8px;padding:10px 12px}'
    + '.uploadmsg a{color:#c56d08;font-weight:800;text-decoration:underline}'
)

if old_upload_style not in career_html:
    raise RuntimeError("Career Pro upload message style was not found.")

career_html = career_html.replace(old_upload_style, new_upload_style, 1)

# Add PDF Summarizer as a third panel using the same existing page classes.
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

if workspace_end not in career_html:
    raise RuntimeError("Career Pro workspace ending was not found.")

career_html = career_html.replace(workspace_end, summary_panel, 1)

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
    "b.dataset.panel==='summary'?'none':'grid';"
    "saveCareerDraft()"
    "});"
)

if old_tab_script not in career_html:
    raise RuntimeError("Original Career Pro tab behavior was not found.")

career_html = career_html.replace(old_tab_script, new_tab_script, 1)

# Replace the old resume upload function with a readable version that:
# 1. shows file size,
# 2. blocks files over 8 MB,
# 3. links large PDFs to EggyPDF Compress PDF,
# 4. saves Career Pro form data before leaving,
# 5. restores a compressed PDF when the user comes back.
old_upload_function = (
    "async function upload(f){$('uploadmsg').textContent='Reading '+f.name+'…';"
    "let form=new FormData();form.append('session_id',session);form.append('resume',f);"
    "try{let r=await fetch(API+'/api/career/pro/extract-resume',{method:'POST',body:form}),"
    "d=await r.json();if(!r.ok||!d.success)throw Error(d.error||'Upload failed.');"
    "$('resume').value=d.resume_text;$('uploadmsg').textContent='✓ '+d.filename+"
    "' extracted successfully ('+d.characters.toLocaleString()+' characters).'}"
    "catch(e){$('uploadmsg').textContent=e.message}}"
)

new_upload_function = r'''const CAREER_STATE_KEY = 'eggypdf_career_pro_draft';
const CAREER_TRANSFER_DB = 'eggypdf_career_transfer';
const CAREER_TRANSFER_STORE = 'files';
const MAX_RESUME_BYTES = 8 * 1024 * 1024;

function formatFileSize(bytes) {
  return (bytes / 1024 / 1024).toFixed(2) + ' MB';
}

function saveCareerDraft() {
  try {
    sessionStorage.setItem(CAREER_STATE_KEY, JSON.stringify({
      resume: $('resume').value,
      job: $('job').value,
      name: $('name').value,
      role: $('role').value,
      company: $('company').value,
      tone: $('tone').value,
      activePanel: document.querySelector('.tab.active')?.dataset.panel || 'opt'
    }));
  } catch (error) {
    console.warn('Could not save Career Pro draft.', error);
  }
}

function restoreCareerDraft() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(CAREER_STATE_KEY) || '{}');

    if (saved.resume != null) $('resume').value = saved.resume;
    if (saved.job != null) $('job').value = saved.job;
    if (saved.name != null) $('name').value = saved.name;
    if (saved.role != null) $('role').value = saved.role;
    if (saved.company != null) $('company').value = saved.company;
    if (saved.tone) $('tone').value = saved.tone;

    if (saved.activePanel) {
      const button = document.querySelector('.tab[data-panel="' + saved.activePanel + '"]');
      if (button) button.click();
    }
  } catch (error) {
    console.warn('Could not restore Career Pro draft.', error);
  }
}

['resume', 'job', 'name', 'role', 'company'].forEach(id => {
  $(id).addEventListener('input', saveCareerDraft);
});
$('tone').addEventListener('change', saveCareerDraft);

function openCareerTransferDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(CAREER_TRANSFER_DB, 1);

    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(CAREER_TRANSFER_STORE)) {
        request.result.createObjectStore(CAREER_TRANSFER_STORE);
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function takeCompressedResume() {
  try {
    const database = await openCareerTransferDatabase();

    const item = await new Promise((resolve, reject) => {
      const transaction = database.transaction(CAREER_TRANSFER_STORE, 'readwrite');
      const store = transaction.objectStore(CAREER_TRANSFER_STORE);
      const request = store.get('career-pro-resume');

      request.onsuccess = () => {
        const value = request.result;
        store.delete('career-pro-resume');
        resolve(value);
      };

      request.onerror = () => reject(request.error);
    });

    database.close();

    if (!item?.blob) return;

    const compressedFile = new File(
      [item.blob],
      item.name || 'compressed-resume.pdf',
      { type: item.blob.type || 'application/pdf' }
    );

    $('uploadmsg').className = 'uploadmsg';
    $('uploadmsg').textContent =
      'Restored compressed resume: ' + compressedFile.name + ' · ' + formatFileSize(compressedFile.size);

    await upload(compressedFile);
  } catch (error) {
    console.warn('Could not restore the compressed resume.', error);
  }
}

async function upload(fileToUpload) {
  const message = $('uploadmsg');
  const sizeLabel = formatFileSize(fileToUpload.size);

  message.className = 'uploadmsg';
  message.textContent = fileToUpload.name + ' · ' + sizeLabel;

  if (fileToUpload.size > MAX_RESUME_BYTES) {
    saveCareerDraft();
    message.className = 'uploadmsg warnsize';

    const isPdf = fileToUpload.name.toLowerCase().endsWith('.pdf');

    if (isPdf) {
      message.innerHTML =
        '<b>' + esc(fileToUpload.name) + ' · ' + esc(sizeLabel) + '</b><br>' +
        'This file is larger than the 8 MB Career Pro limit. ' +
        '<a href="compress.html?from=career-pro" id="compressResumeLink">' +
        'Click here to compress your PDF</a>. Your Career Pro details will stay saved.';

      $('compressResumeLink').onclick = saveCareerDraft;
    } else {
      message.innerHTML =
        '<b>' + esc(fileToUpload.name) + ' · ' + esc(sizeLabel) + '</b><br>' +
        'This file is larger than the 8 MB Career Pro limit. Please reduce it below 8 MB and upload it again.';
    }

    return;
  }

  message.textContent = 'Reading ' + fileToUpload.name + ' · ' + sizeLabel + '…';

  const form = new FormData();
  form.append('session_id', session);
  form.append('resume', fileToUpload);

  try {
    const response = await fetch(API + '/api/career/pro/extract-resume', {
      method: 'POST',
      body: form
    });

    const data = await response.json();

    if (!response.ok || !data.success) {
      throw new Error(data.error || 'Upload failed.');
    }

    $('resume').value = data.resume_text;
    saveCareerDraft();

    message.className = 'uploadmsg';
    message.textContent =
      '✓ ' + data.filename + ' · ' + sizeLabel +
      ' extracted successfully (' + data.characters.toLocaleString() + ' characters).';
  } catch (error) {
    message.className = 'uploadmsg warnsize';
    message.textContent = error.message;
  }
}'''

if old_upload_function not in career_html:
    raise RuntimeError("Original resume upload function was not found.")

career_html = career_html.replace(old_upload_function, new_upload_function, 1)

# PDF Summarizer behavior. The selected PDF also displays its file size.
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
  $('summaryUploadMessage').textContent =
    'Selected: ' + file.name + ' · ' + formatFileSize(file.size);
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
  $('summaryUploadMessage').textContent =
    'Reading and summarizing ' + selectedSummaryPdf.name + ' · ' +
    formatFileSize(selectedSummaryPdf.size) + '…';

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
      '<div class="actions">' +
      '<button class="btn secondary" id="copySummary">Copy Summary</button>' +
      '</div>';

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

restoreCareerDraft();
takeCompressedResume();
'''

career_html = career_html.replace('</script>', summary_script + '\n</script>', 1)
career_file.write_text(career_html, encoding="utf-8")

# -----------------------------------------------------------------------------
# Compress PDF: add a return path only when opened from Career Pro.
# Existing compressor theme and normal user flow remain unchanged.
# -----------------------------------------------------------------------------

main_marker = '<main>\n  <div class="upload-area">'
career_notice = '''<main>
  <div id="careerCompressNotice" style="display:none;margin-bottom:16px;padding:12px 14px;background:var(--brand-light);border:1px solid #f3d594;border-radius:9px;font-size:13px;color:#7c5a13">
    <b>Career Pro file too large?</b> Compress it here. When compression finishes, use <b>Go back to Career Pro</b>. Your previous Career Pro details will still be there.
  </div>
  <div class="upload-area">'''

if main_marker not in compress_html:
    raise RuntimeError("Compress PDF main upload area was not found.")

compress_html = compress_html.replace(main_marker, career_notice, 1)

old_result_button = '<button class="new-btn" onclick="resetTool()">🔄 Compress another</button>'
new_result_buttons = (
    old_result_button
    + '\n    <button class="new-btn" id="careerReturnBtn" style="display:none" '
      'onclick="returnToCareerPro()">Go back to Career Pro</button>'
)

if old_result_button not in compress_html:
    raise RuntimeError("Compress PDF result buttons were not found.")

compress_html = compress_html.replace(old_result_button, new_result_buttons, 1)

old_blob_block = '''    const blob=await res.blob();
    document.getElementById('downloadLink').href=URL.createObjectURL(blob);
    hideEggProgress();document.getElementById('resultCard').style.display='block';document.getElementById('continueSection') && (document.getElementById('continueSection').style.display='block');'''

new_blob_block = '''    const blob=await res.blob();
    document.getElementById('downloadLink').href=URL.createObjectURL(blob);

    if (isCareerProReturn()) {
      await saveCareerCompressedFile(blob, selectedFile?.name);
    }

    hideEggProgress();document.getElementById('resultCard').style.display='block';document.getElementById('continueSection') && (document.getElementById('continueSection').style.display='block');

    const returnButton = document.getElementById('careerReturnBtn');
    if (returnButton) {
      returnButton.style.display = isCareerProReturn() ? 'inline-flex' : 'none';
    }'''

if old_blob_block not in compress_html:
    raise RuntimeError("Compress PDF result handling was not found.")

compress_html = compress_html.replace(old_blob_block, new_blob_block, 1)

old_reset = 'function resetTool(){selectedFile=null;'
new_helpers = r'''function isCareerProReturn() {
  return new URLSearchParams(location.search).get('from') === 'career-pro';
}

function openCareerTransferDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('eggypdf_career_transfer', 1);

    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains('files')) {
        request.result.createObjectStore('files');
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveCareerCompressedFile(blob, originalName) {
  try {
    const database = await openCareerTransferDatabase();
    const baseName = (originalName || 'resume.pdf').replace(/\.pdf$/i, '');
    const fileName = baseName + '-compressed.pdf';

    await new Promise((resolve, reject) => {
      const transaction = database.transaction('files', 'readwrite');
      transaction.objectStore('files').put({
        blob,
        name: fileName,
        size: blob.size,
        createdAt: Date.now()
      }, 'career-pro-resume');

      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });

    database.close();
  } catch (error) {
    console.warn('Could not cache the compressed Career Pro file.', error);
  }
}

function returnToCareerPro() {
  location.href = 'career-pro.html?returned=compressed';
}

function resetTool(){selectedFile=null;'''

if old_reset not in compress_html:
    raise RuntimeError("Compress PDF reset function was not found.")

compress_html = compress_html.replace(old_reset, new_helpers, 1)

script_end = '</script>\n\n<!-- FOOTER -->'
startup_code = '''if (isCareerProReturn()) {
  document.getElementById('careerCompressNotice').style.display = 'block';
}
</script>

<!-- FOOTER -->'''

if script_end not in compress_html:
    raise RuntimeError("Compress PDF script ending was not found.")

compress_html = compress_html.replace(script_end, startup_code, 1)
compress_file.write_text(compress_html, encoding="utf-8")

print("Career Pro final flow built on the existing yellow/white theme.")
