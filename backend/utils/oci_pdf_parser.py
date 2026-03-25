"""
Oracle PaaS/IaaS Global Price List — local PDF parser
======================================================
Extracts pricing rows directly from pdfplumber table data.
No API calls, no LLM.

Parsing rules (derived from annotated PDF layout)
--------------------------------------------------
Each page contains one main table structured as:

  Rows 0-N   Section / sub-section headers (merged cells, mostly None)
  Row H      Column-header row — contains 'Pay as You Go' and
             'Annual Commitment' as cell text
  Row H+1…   Alternating label rows and price rows:

    LABEL row  — service group / sub-group name, no prices (grayed in PDF)
                 The FIRST label row after the header is the section label
                 (category source).  Subsequent label rows refine the name
                 context but do not reset the section.

    PRICE row  — has PAYG price and usually a Part Number (e.g. B95306).

Saving rules
------------
  • A price row WITH a part number  → save one record per stacked entry,
    using the service name from that price row.

  • A price row WITHOUT any part number → save only the FIRST stacked entry,
    service name = section_label (first label after header).

  • Annual Commitment → saved as a SECOND record ONLY if the price differs
    from Pay as You Go.  Otherwise one record (PAYG) is enough.

  • Metric Minimum + Additional Information → concatenated into specifications.

  • Part Number → saved in specifications for reference.

  • Stacked entries in one cell (name\\nprice\\npart) = multiple parallel SKUs.
    Each gets its own record when it has a part number.
"""

from __future__ import annotations

import os
import re
import tempfile
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category inference
# ---------------------------------------------------------------------------

# Name-based rules — most specific first.  First match wins.
_NAME_CATEGORY_RULES: List[Tuple[List[str], str]] = [
    # Storage billing overrides "database" in the name
    (["object storage", "block volume", "archive storage", "file storage",
      "backup cloud", "backup storage", "data transfer"],
     "Storage"),
    # Networking
    (["fastconnect", "load balancer", "dns traffic", "dns", "vpn",
      "network firewall", "web application firewall", "waf", "health check",
      "network cloud"],
     "Networking"),
    # AI / ML
    (["generative ai", "ai service", "language service", "vision service",
      "speech service", "forecasting", "anomaly detection",
      "document understanding"],
     "AI/ML"),
    # Container / DevOps
    (["kubernetes", " oke ", "container engine", "container instance",
      "functions", "api gateway", "service mesh", "devops"],
     "Containers/DevOps"),
    # Analytics
    (["analytics", "big data", "data integration", "goldengate",
      "data science", "streaming"],
     "Analytics"),
    # Database engines (after storage overrides)
    (["autonomous database", "exadata", "mysql", "postgresql", "nosql",
      "heatwave", "database service", "db service"],
     "Database"),
    (["database"], "Database"),
    # Compute shapes / infrastructure (specific shapes first, then generic)
    (["vm.standard", "bm.standard", "vm.dense", "bm.dense",
      "vm.gpu", "bm.gpu", "vm.optimized", "vmware", "hpc",
      "compute cloud", "compute service", "gpu cloud", " gpu "],
     "Compute"),
    # Application Development
    (["application development", "blockchain", "digital assistant",
      "visual builder", "mobile hub", "integration cloud",
      "process automation", "weblogic"],
     "Application Development"),
    # Security / Observability
    (["vault", "identity", "security zone", "bastion",
      "monitoring", "logging", "events", "notifications"],
     "Security/Observability"),
    # Content Management
    (["webcenter", "content management", "media service"],
     "Content Management"),
]

# Page-text fallback — coarser, used only when the name gives no signal
_PAGE_CATEGORY_MAP: List[Tuple[List[str], str]] = [
    (["autonomous database", "mysql", "postgresql", "exadata", "database"], "Database"),
    (["object storage", "block volume", "archive storage", "file storage"], "Storage"),
    (["compute cloud", "compute service", "vm.standard", "bm.standard"], "Compute"),
    (["fastconnect", "load balancer", "dns", "networking"], "Networking"),
    (["analytics", "big data", "data integration", "goldengate"], "Analytics"),
    (["generative ai", "ai service"], "AI/ML"),
    (["container", "kubernetes", "functions", "devops"], "Containers/DevOps"),
    (["monitoring", "logging", "vault", "security"], "Security/Observability"),
]


def _infer_category(service_name: str, page_text: str = '') -> str:
    """
    Infer category from service name first, fall back to page text.
    Using the name is much more accurate — e.g. 'Oracle Database Backup Cloud
    - Object Storage' → Storage, not Database.
    """
    low = service_name.lower()
    for keywords, category in _NAME_CATEGORY_RULES:
        if any(kw in low for kw in keywords):
            return category
    low_page = page_text.lower()
    for keywords, category in _PAGE_CATEGORY_MAP:
        if any(kw in low_page for kw in keywords):
            return category
    return "Other"


# ---------------------------------------------------------------------------
# Price / text helpers
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r'\d[\d,]*(?:\.\d+)?')
_PART_RE   = re.compile(r'\bB\d{5,6}\b')   # Oracle part numbers like B95306

# Pattern that matches Oracle's embedded price suffix inside name cells:
#   "Oracle DB Service - Standard Edition** 0.2150 0.2150"
#                                         ^^^^^^^^^^^^^^^^ — this is stripped
_EMBEDDED_PRICE_RE = re.compile(r'\*+\s+\d[\d,]*\.\d+\s+\d[\d,]*\.\d+\s*$')

# Footnote / legal note lines inside name cells start with "(" — e.g.:
#   "(**Limited Availability: See Note 11)"
_FOOTNOTE_LINE_RE = re.compile(r'^\s*\(')


def _parse_price(text: str) -> Optional[float]:
    """Return the first number found in a cell, or None."""
    if not text:
        return None
    t = text.strip()
    if t.lower() in ('', 'n/a', '-', '—', 'tbd', 'free', 'always free',
                     'contact', 'none', 'null'):
        return None
    m = _NUMBER_RE.search(t)
    if not m:
        return None
    try:
        return float(m.group().replace(',', ''))
    except ValueError:
        return None


def _is_valid_part(text: str) -> bool:
    """True if the text looks like an Oracle part number (B + 5-6 digits)."""
    return bool(text and _PART_RE.search(text.strip()))


def _split_multiline(text: Optional[str]) -> List[str]:
    """Split a cell containing multiple stacked values separated by \\n."""
    if not text:
        return []
    return [s.strip() for s in str(text).split('\n') if s.strip()]


def _clean_name_lines(lines: List[str]) -> List[str]:
    """
    Clean a list of lines from a stacked Oracle name cell.

    Three issues appear in Oracle's PDF:

    1. WORD-WRAP CONTINUATIONS — long service names wrap mid-word inside the
       cell, producing a fragment on the next line that starts with a lowercase
       letter:
         ["... (% applied to consumption, with", "minimum)"]
       → rejoin to the previous line so it reads as one name.

    2. EMBEDDED PRICES — the name cell sometimes contains the price appended
       to each service name (likely from column overflow):
         "Oracle DB Cloud Service - Standard Edition** 0.2150 0.2150"
       → strip everything after the "** <price> <price>" suffix.

    3. FOOTNOTE LINES — after each name there may be a legal note:
         "(**Limited Availability: See Note 11)"
       → drop any line that starts with '(' (footnote / parenthetical).

    Returns the filtered, cleaned list.  Falls back to the original list
    if all lines would be filtered (so we never lose all names).
    """
    # --- Pass 1: rejoin word-wrap continuations ---
    # A line is a continuation if its first non-space character is lowercase.
    joined: List[str] = []
    for line in lines:
        stripped = line.strip()
        if joined and stripped and stripped[0].islower():
            # This is a continuation of the previous line
            joined[-1] = joined[-1] + ' ' + stripped
        else:
            joined.append(line)

    # --- Pass 2: filter footnotes and strip embedded prices ---
    result: List[str] = []
    for line in joined:
        # Drop footnote / legal lines (start with open parenthesis)
        if _FOOTNOTE_LINE_RE.match(line):
            continue
        # Strip embedded price suffix: "** 0.2150 0.2150" at end of line
        clean = _EMBEDDED_PRICE_RE.sub('', line)
        # Also strip any trailing asterisks / spaces left over
        clean = re.sub(r'[\s*]+$', '', clean).strip()
        if clean and len(clean) > 2:
            result.append(clean)
    # Fallback: if we filtered everything, return original (caller will handle)
    return result if result else lines


def _infer_billing_type(metric: str, service_category: str = '') -> str:
    """
    Derive a short billing-type category from the raw metric string.

    The result becomes the ``instance_type`` column so the UI can group rows
    by *what* is being billed rather than repeating the service name.

    Examples
    --------
    "Per OCPU Per Hour"                     → "Compute"
    "Per ECPU Per Hour"                     → "Compute"
    "Gigabyte Storage Capacity Per Month"   → "Storage"
    "Per GB Data Transfer Out"              → "Network"
    "Per Million API Calls"                 → "API/Request"
    "Per Support Request"                   → "Support"
    "Bring Your Own License"                → "License"
    ""  (no metric, but category = "Database") → "Database"
    """
    low = (metric or '').lower()

    # Compute — OCPU/ECPU, per-hour instance billing
    if any(kw in low for kw in ('ocpu', 'ecpu', 'vcpu', 'vcore',
                                 'node per hour', 'instance per hour',
                                 'per hour', '1 hour', 'per compute hour')):
        return 'Compute'

    # Storage — capacity, block, object, archive
    if any(kw in low for kw in ('gigabyte', 'terabyte', ' gb ', 'gb/', 'per gb',
                                 ' tb ', 'tb/', 'per tb', 'storage capacity',
                                 'per month', 'gb month', 'tb month')):
        return 'Storage'

    # Network — data transfer / bandwidth
    if any(kw in low for kw in ('transfer', 'bandwidth', 'egress', 'ingress',
                                 'outbound', 'inbound', 'data out', 'data in')):
        return 'Network'

    # API / request-based billing
    if any(kw in low for kw in ('request', 'api call', 'query', 'per million',
                                 'per thousand', 'per 10k', 'transaction',
                                 'message', 'event', 'call')):
        return 'API/Request'

    # License
    if any(kw in low for kw in ('license', 'byol', 'bring your own')):
        return 'License'

    # Support
    if 'support' in low:
        return 'Support'

    # Fall back to the service_category so it's never blank
    if service_category:
        return service_category

    return 'Other'


def _normalize_metric_lines(lines: List[str]) -> List[str]:
    """
    Rejoin metric fragments split across lines by Oracle's PDF layout.
    E.g. ['Gigabyte Storage Capacity Per', 'Month'] → ['Gigabyte Storage Capacity Per Month']
    """
    result: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (line.lower().endswith(' per') or line.lower() == 'per') and i + 1 < len(lines):
            next_low = lines[i + 1].lower().strip()
            if next_low in ('hour', 'month', 'day', 'year', 'unit', 'ocpu', 'ecpu',
                            'gb', 'tb', 'request', 'query', 'node', 'instance',
                            'transaction', 'million', 'session', 'stream'):
                result.append(line + ' ' + lines[i + 1])
                i += 2
                continue
        result.append(line)
        i += 1
    return result


# ---------------------------------------------------------------------------
# Header-row detection
# ---------------------------------------------------------------------------

def _find_header(table: List[List]) -> Tuple[int, Dict[str, int]]:
    """
    Scan every row for the column-header row that contains 'Pay as You Go'
    and 'Annual Commitment'.  Returns (header_row_index, col_map).

    col_map keys:
        name_col         — service name column (almost always col 1)
        payg_col         — Pay as You Go price
        annual_col       — Annual Commitment price  (-1 if absent)
        metric_col       — pricing unit / metric    (-1 if absent)
        metric_min_col   — metric minimum           (-1 if absent)
        additional_col   — additional information   (-1 if absent)
        part_col         — part number              (-1 if absent)
    """
    for i, row in enumerate(table):
        cells = [str(c).strip() if c else '' for c in row]
        flat  = ' '.join(cells).lower()
        if 'pay as you go' in flat and ('annual' in flat or 'commitment' in flat):
            col_map: Dict[str, int] = {
                'name_col':       1,
                'payg_col':      -1,
                'annual_col':    -1,
                'metric_col':    -1,
                'metric_min_col':-1,
                'additional_col':-1,
                'part_col':      -1,
            }
            for j, cell in enumerate(cells):
                cl = cell.lower()
                if 'pay as you go' in cl:
                    col_map['payg_col'] = j
                elif 'annual' in cl and ('commit' in cl or 'commitment' in cl):
                    col_map['annual_col'] = j
                elif cl in ('metric', 'metrics'):
                    col_map['metric_col'] = j          # exact match — not 'Metric Minimum'
                elif 'metric' in cl and 'minimum' in cl:
                    col_map['metric_min_col'] = j
                elif 'additional' in cl and 'information' in cl:
                    col_map['additional_col'] = j
                elif 'part' in cl and 'number' in cl:
                    col_map['part_col'] = j

            if col_map['payg_col'] != -1:
                return i, col_map

    return -1, {}


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(
    name:            str,
    payg_val:        float,
    annual_val:      Optional[float],
    metric:          str,
    metric_min:      str,
    additional_info: str,
    part_number:     str,
    service_category:str,
    doc_name:        str,
    region:          str,
) -> List[Dict]:
    """
    Build 1 or 2 pricing records for a single SKU.

    Returns two records (PAYG + Annual) only when annual_val differs from
    payg_val.  Otherwise returns one record (PAYG only).
    """
    # ---------- hourly vs monthly classification ----------
    norm       = _normalize_metric_lines([metric])[0] if metric else ''
    metric_low = norm.lower()
    is_hourly  = ('hour'  in metric_low or 'ocpu' in metric_low or
                  'ecpu'  in metric_low or 'node per hour' in metric_low)
    is_monthly = ('month' in metric_low or 'gb'   in metric_low or
                  'tb'    in metric_low or 'gigabyte' in metric_low or
                  'terabyte' in metric_low or 'data transfer' in metric_low or
                  'per query' in metric_low or 'per million' in metric_low or
                  'per request' in metric_low)

    if is_hourly:
        price_h = payg_val
        price_m = round(payg_val * 730, 6)
    elif is_monthly:
        price_h = round(payg_val / 730, 6)
        price_m = payg_val
    else:
        # Heuristic: ≤ $5 → hourly (typical OCPU/ECPU rate), > $5 → monthly
        if payg_val <= 5:
            price_h = payg_val
            price_m = round(payg_val * 730, 6)
        else:
            price_h = round(payg_val / 730, 6)
            price_m = payg_val

    # ---------- specifications ----------
    specs: Dict = {}
    if metric:
        specs['metric'] = metric
    if metric_min and metric_min not in ('-', '—', ''):
        specs['metric_minimum'] = metric_min
    if additional_info and additional_info not in ('-', '—', ''):
        specs['additional_info'] = additional_info
    if part_number:
        specs['part_number'] = part_number

    # Normalise the metric string before storing so multi-line fragments
    # (e.g. "Gigabyte Storage Capacity Per\nMonth") are already joined.
    norm_metric = norm if norm else metric

    # Derive a short billing-type category for the instance_type column.
    billing_type = _infer_billing_type(norm_metric, service_category)

    base = {
        'cloud_provider':   'OCI',
        'service_category': service_category,
        'service_name':     name,
        'instance_type':    billing_type,     # billing-type category, not the name
        'metric':           norm_metric or None,   # promoted to its own column
        'region':           region,
        'currency':         'USD',
        'specifications':   specs,
        'source_api':       f'OCI PDF Local: {doc_name}',
    }

    records = [{
        **base,
        'price_per_hour':  price_h,
        'price_per_month': price_m,
        'pricing_model':   'Pay as You Go',
        'features':        ['Pay as You Go'],
    }]

    # Add Annual Commitment only when the price is genuinely different
    if annual_val is not None and annual_val != payg_val:
        if is_hourly:
            ann_h = annual_val
            ann_m = round(annual_val * 730, 6)
        elif is_monthly:
            ann_h = round(annual_val / 730, 6)
            ann_m = annual_val
        else:
            if annual_val <= 5:
                ann_h = annual_val
                ann_m = round(annual_val * 730, 6)
            else:
                ann_h = round(annual_val / 730, 6)
                ann_m = annual_val

        records.append({
            **base,
            'price_per_hour':  ann_h,
            'price_per_month': ann_m,
            'pricing_model':   'Annual Commitment',
            'features':        ['Annual Commitment'],
        })

    return records


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------

def _parse_oracle_table(
    table:     List[List],
    page_text: str,
    doc_name:  str,
    region:    str,
) -> List[Dict]:
    """Parse one pdfplumber table using Oracle's label-row / price-row format."""

    header_idx, col_map = _find_header(table)
    if header_idx == -1:
        return []

    name_col       = col_map['name_col']
    payg_col       = col_map['payg_col']
    annual_col     = col_map.get('annual_col',     -1)
    metric_col     = col_map.get('metric_col',     -1)
    metric_min_col = col_map.get('metric_min_col', -1)
    additional_col = col_map.get('additional_col', -1)
    part_col       = col_map.get('part_col',       -1)

    # Coarse page-level category — only used when the name gives no signal
    page_category = _infer_category('', page_text)

    results:       List[Dict] = []
    pending_name:  Optional[str] = None   # label row saved for the next price row
    section_label: Optional[str] = None   # FIRST label after the header (Row 12)
    pending_metric:     str = ''
    pending_metric_min: str = ''
    pending_additional: str = ''

    def _cell(row: List, idx: int) -> str:
        if idx < 0 or idx >= len(row):
            return ''
        return str(row[idx]).strip() if row[idx] else ''

    for row in table[header_idx + 1:]:
        name_cell       = _cell(row, name_col)
        payg_cell       = _cell(row, payg_col)
        annual_cell     = _cell(row, annual_col)     if annual_col     >= 0 else ''
        metric_cell     = _cell(row, metric_col)     if metric_col     >= 0 else ''
        metric_min_cell = _cell(row, metric_min_col) if metric_min_col >= 0 else ''
        additional_cell = _cell(row, additional_col) if additional_col >= 0 else ''
        part_cell       = _cell(row, part_col)       if part_col       >= 0 else ''

        has_name  = bool(name_cell and len(name_cell) > 2)
        has_price = bool(_parse_price(payg_cell) or _parse_price(annual_cell))

        if not has_name and not has_price:
            continue   # completely empty row

        # Carry forward any non-empty context cells
        if metric_cell:
            pending_metric     = metric_cell
        if metric_min_cell:
            pending_metric_min = metric_min_cell
        if additional_cell:
            pending_additional = additional_cell

        if has_name and not has_price:
            # Label row — save as pending name; first one becomes section_label
            pending_name = name_cell
            if section_label is None:
                section_label = name_cell
            continue

        # --- Price row ---
        if has_name:
            service_name = name_cell      # name and price on the same row
        elif pending_name:
            service_name = pending_name
        else:
            continue   # price with no associated name

        pending_name = None   # consumed

        # Skip footnotes / legal notes
        if re.match(r'^[\(\*]', service_name):
            continue

        # Strip stray part-number suffixes that bleed into the name cell
        service_name = re.sub(r'\s+B\d{5,6}$', '', service_name).strip()

        # ---- Expand stacked entries ----
        raw_name_lines = _split_multiline(service_name) or [service_name]
        # Clean name lines: remove footnote lines and strip embedded prices
        names        = _clean_name_lines(raw_name_lines) or raw_name_lines
        paygs        = _split_multiline(payg_cell)
        annuals      = _split_multiline(annual_cell)
        part_numbers = _split_multiline(part_cell)

        # Fallback: some Oracle pages embed part numbers inside the Additional
        # Information cell (e.g. "Minimum of 48 hours. B91535\n...") instead of
        # the dedicated Part Number column.  Extract them when part_col is empty.
        raw_additional = additional_cell or ''
        if not part_numbers and raw_additional:
            embedded = _PART_RE.findall(raw_additional)
            if embedded:
                part_numbers = embedded
                # Remove part number tokens from the additional text so they
                # do not show up literally in the specifications.
                raw_additional = _PART_RE.sub('', raw_additional).strip()

        raw_metrics  = _split_multiline(metric_cell) or _split_multiline(pending_metric)
        metrics      = _normalize_metric_lines(raw_metrics) if raw_metrics else []
        metric_mins  = _split_multiline(metric_min_cell) or _split_multiline(pending_metric_min)
        additionals  = _split_multiline(raw_additional) or _split_multiline(pending_additional)

        # Broadcast single-value lists to match the longest list
        n = max(len(names), len(paygs), len(part_numbers) if part_numbers else 0)

        def _at(lst, i):
            if not lst:
                return ''
            return lst[i] if i < len(lst) else lst[-1]

        any_part = any(_is_valid_part(_at(part_numbers, i)) for i in range(n))

        # When names has only ONE element but there are multiple part numbers,
        # we need to differentiate each entry.  We'll append "(part_number)" to
        # make each record's name unique.
        one_name_many_parts = (len(names) == 1 and len(part_numbers) > 1)

        for idx in range(n):
            raw_name   = _at(names, idx)
            payg_raw   = _at(paygs, idx)
            annual_raw = _at(annuals, idx)
            part_num   = _at(part_numbers, idx)
            metric     = _at(metrics, idx)
            metric_min = _at(metric_mins, idx)
            additional = _at(additionals, idx)

            # ---- Saving rule ----
            if any_part:
                # Row has part numbers — save entries that have a valid part number
                if not _is_valid_part(part_num):
                    continue
                base_name = raw_name if raw_name and len(raw_name) > 2 else (section_label or '')
                # If there's only one base name for multiple parts, differentiate by
                # appending the part number so each SKU gets its own unique record
                if one_name_many_parts and _is_valid_part(part_num):
                    name = f"{base_name} ({part_num})"
                else:
                    name = base_name
            else:
                # No part numbers in this row — save only the first stacked entry.
                # Use the most specific pending name (raw_name from label row), falling
                # back to the section label if no specific name is available.
                if idx > 0:
                    break
                name = raw_name or section_label

            if not name or len(name) < 3:
                continue
            if re.match(r'^[\(\*]', name):
                continue

            payg_val   = _parse_price(payg_raw)
            annual_val = _parse_price(annual_raw)

            if not payg_val and not annual_val:
                continue

            if payg_val and not annual_val:
                annual_val = payg_val
            if annual_val and not payg_val:
                payg_val = annual_val

            # Category resolution (most → least accurate).
            # All name-rule steps use NO page text so a page containing "database"
            # doesn't pollute unrelated services.  Page text is last resort only.
            #
            # 1. Service name — most specific ("Block Volume Storage" → Storage,
            #    even when the section label says "Compute Cloud@Customer")
            # 2. Section label — contextual fallback ("Oracle Compute Cloud Services")
            # 3. Page text    — coarse last resort
            service_category = _infer_category(name)                  # name rules only
            if service_category == 'Other':
                service_category = _infer_category(section_label or '') # name rules only
            if service_category == 'Other' and page_category != 'Other':
                service_category = page_category                        # page text fallback

            records = _build_record(
                name=name,
                payg_val=payg_val,
                annual_val=annual_val,
                metric=metric,
                metric_min=metric_min,
                additional_info=additional,
                part_number=part_num if _is_valid_part(part_num) else '',
                service_category=service_category,
                doc_name=doc_name,
                region=region,
            )
            results.extend(records)

    return results


# ---------------------------------------------------------------------------
# Raw-character name extraction (for floating names outside table cells)
# ---------------------------------------------------------------------------

def _extract_floating_part_names(page) -> Dict[str, str]:
    """
    Oracle's PDF sometimes places variant-level service names (e.g.
    "Oracle Base Database Service - Standard - ECPU") as floating text
    that does NOT fall inside any table cell.  pdfplumber therefore returns
    None for the name column of those price rows.

    This function scans the raw page characters, groups them by y-position,
    and for each line that contains a part-number in the RIGHTMOST column
    (x > 85% of page width) it extracts the name text from the LEFT portion
    of that line (x < 32% of page width).

    Using x-position-based extraction (instead of regex) avoids false negatives
    caused by part numbers being concatenated with adjacent text in the raw
    character stream (e.g. "MemoryB90569").

    Oracle's pages are 792pt wide:
      • Name column: x ≈ 72–195  (< 32% ≈ 253)
      • Part number column: x ≈ 693–713  (> 85% ≈ 673)

    Returns a dict { part_number: service_name }.
    """
    from collections import defaultdict

    chars = getattr(page, 'chars', [])
    if not chars:
        return {}

    page_width   = float(page.width or 792)
    name_x_right = page_width * 0.32   # right edge of the name column
    part_x_left  = page_width * 0.85   # left edge of the part-number column

    # Group chars by y-bucket (3-point buckets match Oracle's row spacing)
    by_y: Dict[int, list] = defaultdict(list)
    for c in chars:
        y_bucket = round(float(c['top']) / 3) * 3
        by_y[y_bucket].append(c)

    part_to_name: Dict[str, str] = {}
    for _y, row_chars in by_y.items():
        # Extract part numbers from the rightmost column by x-position
        part_chars = sorted(
            [c for c in row_chars if c['x0'] >= part_x_left],
            key=lambda c: c['x0'],
        )
        part_text = ''.join(c['text'] for c in part_chars).strip()
        parts = _PART_RE.findall(part_text)
        if not parts:
            continue

        # Extract service name from the leftmost column by x-position
        name_chars = sorted(
            [c for c in row_chars if c['x0'] < name_x_right],
            key=lambda c: c['x0'],
        )
        name_text = ''.join(c['text'] for c in name_chars).strip()

        # Only keep genuine service names (start with uppercase, > 5 chars)
        if name_text and len(name_text) > 5 and name_text[0].isupper():
            for part in parts:
                if part not in part_to_name:   # first occurrence wins
                    part_to_name[part] = name_text

    return part_to_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_oci_pricing_pdf(
    pdf_path: str,
    doc_name: str = '',
    region:   str = 'eu-zurich-1',
) -> List[Dict]:
    """
    Extract all pricing from an Oracle PaaS/IaaS Global Price List PDF.
    Returns a flat list of dicts compatible with bulk_insert_pricing_data().
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError('pip install pdfplumber')

    if not doc_name:
        doc_name = os.path.basename(pdf_path)

    results:   List[Dict] = []
    seen_keys: Dict        = {}   # key → record, for smart deduplication

    with pdfplumber.open(pdf_path) as pdf:
        logger.info(f"Parsing {len(pdf.pages)} pages of '{doc_name}'")
        pages_with_data = 0

        for page in pdf.pages:
            page_text    = page.extract_text() or ''
            tables       = page.extract_tables()
            # Build part→name lookup from raw chars for this page.
            # Used to resolve variant names that pdfplumber misses because
            # Oracle places them as floating text outside the table cells.
            floating_names = _extract_floating_part_names(page)

            for table in tables:
                rows = _parse_oracle_table(table, page_text, doc_name, region)
                if rows:
                    pages_with_data += 1

                # Replace "(B#####)" placeholder names with the real
                # variant names extracted from raw page characters.
                for row in rows:
                    part = row.get('specifications', {}).get('part_number', '')
                    if part and part in floating_names:
                        real_name = floating_names[part]
                        # Only replace if the current name looks like our
                        # placeholder (ends with "(B#####)") or is just the
                        # section label without variant info
                        current = row['service_name']
                        if current.endswith(f'({part})') or \
                                (real_name.lower().startswith(current.lower().split('(')[0].strip().lower())
                                 and real_name != current):
                            row['service_name'] = real_name
                            # instance_type stays as the billing-type category
                            # (set in _build_record); we do NOT overwrite it here

                for row in rows:
                    part = row.get('specifications', {}).get('part_number', '')
                    if part:
                        # Part-number keyed dedup: same part+model → keep last
                        # (later pages often have better metric context, so the
                        # last record for a given part is generally the best one)
                        key = ('part', part, row.get('pricing_model', ''))
                    else:
                        key = ('name', row['service_name'],
                               row.get('pricing_model', ''), row['price_per_hour'])

                    if key in seen_keys:
                        # Replace the previous record for this key with the new
                        # one only when it has more complete metric information
                        prev = seen_keys[key]
                        if prev.get('specifications', {}).get('metric') and \
                                not row.get('specifications', {}).get('metric'):
                            continue   # keep the one with metric info
                        # Remove the old entry from results
                        try:
                            results.remove(seen_keys[key])
                        except ValueError:
                            pass

                    seen_keys[key] = row
                    results.append(row)

        payg_count   = sum(1 for r in results if r.get('pricing_model') == 'Pay as You Go')
        annual_count = sum(1 for r in results if r.get('pricing_model') == 'Annual Commitment')
        logger.info(
            f"'{doc_name}': {pages_with_data} pages with pricing, "
            f"{payg_count} PAYG records, {annual_count} Annual records "
            f"({annual_count} services have a different annual price)"
        )

    # Post-processing: remove no-part records when a record with the same
    # service name and price already exists WITH a part number.
    # This cleans up cases where the same service appears on multiple pages,
    # once with a part number in the part column and once without (the part
    # was embedded in additional info and couldn't be matched to that page).
    name_price_with_part: set = {
        (r['service_name'], r['price_per_hour'])
        for r in results
        if r.get('specifications', {}).get('part_number')
    }
    before = len(results)
    results = [
        r for r in results
        if r.get('specifications', {}).get('part_number')            # has a part — always keep
        or (r['service_name'], r['price_per_hour']) not in name_price_with_part  # no part, but no duplicate
    ]
    if len(results) < before:
        logger.info(f"Removed {before - len(results)} no-part duplicate records")

    return results


def parse_oci_pricing_pdf_from_bytes(
    pdf_bytes: bytes,
    doc_name:  str = 'oci_pricing.pdf',
    region:    str = 'eu-zurich-1',
) -> List[Dict]:
    """Same as parse_oci_pricing_pdf() but accepts raw bytes."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        return parse_oci_pricing_pdf(tmp_path, doc_name=doc_name, region=region)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
