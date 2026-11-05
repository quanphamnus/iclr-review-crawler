# OpenReview review snapshotter (ICLR & friends)

Chụp lại **toàn bộ review ngay thời điểm chúng được public** (bản v1), rồi về sau
chụp tiếp bản sau rebuttal và **diff** hai bản để xem review nào bị sửa, điểm nào
bị thay đổi.

Mỗi lần chạy tạo một snapshot **bất biến**, có timestamp: JSONL thô đúng như API
trả về, kèm CSV phẳng và `manifest.json` có sha256 từng file + hash nội dung từng
review (để sau này đối chiếu không cần tin vào `tmdate` của OpenReview).

---

## 0. Tình trạng hiện tại (kiểm tra lúc 2026-11-03)

| Hạng mục | Trạng thái |
|---|---|
| Venue sắp có review | `ICLR.cc/2027/Conference` — ICLR 2027, San Francisco, 23/04/2027 |
| Invitation `ICLR.cc/2027/Conference/-/Submission` | **đã hết hạn** → vòng nộp bài đã đóng |
| Invitation `ICLR.cc/2027/Conference/-/Official_Review` | **đã tồn tại nhưng Guest chưa đọc được** → review **chưa** public |
| `review_name` / `rating` / `confidence` | `Official_Review` / `rating` / `confidence` |
| `Author_Rebuttal` | chưa được tạo |

> ICLR 2026 (Rio) đã diễn ra tháng 4/2026 rồi, nên "ICLR năm nay sắp có review" =
> **ICLR 2027**. Nếu ý bạn là venue khác, chỉ cần đổi `--venue`, mọi script đều
> đọc cấu hình venue động (tên field review, rating, các venueid…).

## 1. Bắt buộc: tài khoản OpenReview

OpenReview **đã chặn truy cập vô danh vào `/notes`** (trả về
`ChallengeRequiredError` — bot challenge). Không có cách lách nào hợp lệ; phải
dùng token của một tài khoản thật. Tài khoản free, chỉ cần đăng ký là đọc được
mọi thứ public.

```bash
export OPENREVIEW_USERNAME='email@cua.ban'
export OPENREVIEW_PASSWORD='mat-khau'
```

Hoặc lưu file (chỉ mình đọc được):

```bash
mkdir -p ~/.openreview && printf '{"username":"email@cua.ban","password":"mat-khau"}' > ~/.openreview/credentials.json && chmod 600 ~/.openreview/credentials.json
```

## 2. Cài

```bash
pip install -r requirements.txt
```

## 3. Kiểm tra trước (không tải gì cả)

```bash
python3 check_setup.py --venue ICLR.cc/2027/Conference
```

In ra: login OK chưa, số paper, số review đang thấy được, review đã public chưa,
và gợi ý lệnh tiếp theo. Dòng `VERDICT` nói rõ "reviews ARE visible" hay chưa.

## 4. Để sẵn, tự chạy ngay khi review mở

```bash
nohup python3 watch_and_crawl.py \
  --venue ICLR.cc/2027/Conference \
  --interval 300 \
  --followups 24h,7d,21d \
  > /dev/null 2>&1 &
```

- Mỗi 5 phút hỏi API: có bao nhiêu review đang đọc được.
- **Chỉ nổ** khi `>= --min-count` (mặc định 50) review **và** có ít nhất 1 review
  `readers = everyone`. Nhờ vậy review của chính paper bạn, hoặc review bạn tự
  viết (bạn thấy sớm hơn mọi người) sẽ **không** làm nó bắn sớm và chụp mất bản
  thiếu. Muốn bỏ điều kiện public: `--no-require-public`.
- Nổ xong crawl luôn, snapshot được gắn nhãn `first-release`.
- `--followups 24h,7d,21d` tự chụp thêm các bản sau để so sánh rebuttal.
- Tiến độ ghi ở `watch.log` + `watch_state.json`, restart lại không chụp trùng.
- Muốn chạy bằng cron thay vì tiến trình thường trú:

```bash
*/5 * * * * cd /duong/dan/iclr-review-crawler && OPENREVIEW_USERNAME=... OPENREVIEW_PASSWORD=... python3 watch_and_crawl.py --once >> cron.log 2>&1
```

- Gắn thông báo khi xong (Telegram/Slack/mail…):

```bash
python3 watch_and_crawl.py --notify-cmd 'echo "reviews crawled -> $SNAPSHOT_DIR" | mail -s ICLR you@example.com'
```

## 5. Hoặc chạy tay khi thấy review đã mở

```bash
python3 crawl_reviews.py --venue ICLR.cc/2027/Conference --label first-release
```

Bị ngắt giữa đường (mạng, Ctrl-C, hết pin) thì chạy lại đúng snapshot đó, nó
tiếp tục từ cursor đã lưu, không tải lại và không trùng note:

```bash
python3 crawl_reviews.py --resume snapshots/ICLR_cc_2027_Conference/20261120T<...>_first-release
```

Tuỳ chọn hay dùng:

| Cờ | Ý nghĩa |
|---|---|
| `--kinds review,meta_review,decision` | mặc định; `--kinds all` thêm `comment`, `rebuttal` |
| `--limit 500` | chụp thử 500 note mỗi stream (manifest sẽ ghi `partial: true`) |
| `--sleep 0.25` | nghỉ giữa các trang, cho lịch sự với server |
| `--skip-submissions` | không tải paper (mất title/abstract đi kèm) |
| `--replies-mode` | `parent` (1 query gộp/loại), `forum` (đi theo reply từng paper), `auto` = mặc định |
| `--no-gzip` | ghi `.jsonl` thường cho dễ `grep` |

## 6. So bản đầu với bản sau rebuttal

```bash
python3 diff_snapshots.py \
  snapshots/ICLR_cc_2027_Conference/<...>_first-release \
  snapshots/ICLR_cc_2027_Conference/<...>_followup-24h
```

Sinh `diff.json` + `diff.md` trong snapshot sau:

- review **thêm / mất / bị sửa** (so bằng sha256 nội dung, không tin `tmdate`),
- bảng **điểm thay đổi** (trước → sau, delta, link forum, lên/xuống/trung bình),
- unified diff từng field text (`weaknesses`, `summary`…) để thấy đúng chỗ reviewer sửa chữ.

## 7. Snapshot có gì

```
snapshots/ICLR_cc_2027_Conference/20261120T031500Z_first-release/
├── raw/
│   ├── submissions.jsonl.gz    # note paper, nguyên văn API
│   ├── reviews.jsonl.gz        # note review, nguyên văn API  <- bản gốc để lưu trữ
│   ├── meta_reviews.jsonl.gz
│   └── decisions.jsonl.gz
├── reviews.csv        # 1 dòng/review: paper_number, title, reviewer, rating_num,
│                      # confidence_num, mọi field content, content_sha256, cdate/tmdate...
├── papers.csv         # 1 dòng/paper: n_reviews, danh sách rating, mean/min/max, link forum
├── venue_config.json  # cấu hình venue lúc chụp
├── manifest.json      # số lượng, sha256 từng file, thời gian, ai chụp, tham số đã dùng
├── _progress.json     # cursor để resume
└── crawl.log
```

`reviews.csv` sinh cột **động** theo đúng form review của năm đó, nên form ICLR
2027 có đổi field gì cũng không mất dữ liệu.

## 8. Tài nguyên

Cách lấy review là **một query gộp** theo `parent_invitations`, phân trang bằng
cursor 1000 note/request — khoảng **100–150 request** cho cả ICLR (~25k paper,
~100k review), xong trong vài phút. Nếu API không trả theo cách đó, script tự
chuyển sang đi theo reply của từng paper (`details=directReplies`).

Chuẩn bị khoảng **1–2 GB** đĩa trống cho một snapshot đầy đủ (raw đã gzip
~100–200 MB, CSV thêm tương đương).

## 9. Tự kiểm tra (không cần mạng, không cần tài khoản)

```bash
python3 selftest.py
```

Dựng client giả 2.500 paper / 10.000 review rồi chạy thật cả pipeline: phân
trang nhiều trang, gộp nhiều venueid, stream rỗng, cắt `--limit` + resume không
trùng/không hở, CSV multi-line, parse `"8: marginal"` → `8.0`, đường dự phòng
directReplies, 4 ca chặn bắn sớm của watcher, và diff phát hiện đúng số review
thêm/sửa/đổi điểm. 44 assertion, hiện **pass hết**.

## 10. Giới hạn đã biết

- Phải có tài khoản OpenReview (xem mục 1).
- `--replies-mode forum` chỉ thấy reply **trực tiếp của paper** (review là
  một), không thấy comment lồng dưới review. Đường mặc định `parent` thì lấy đủ.
- Review bị **xoá hẳn** giữa hai lần chụp sẽ hiện ở `removed_ids`; OpenReview
  thường chỉ sửa chứ ít xoá.
- Chỉ chụp được những gì tài khoản của bạn đọc được. Trước ngày public, bạn chỉ
  thấy review của paper mình / review mình viết — đó là lý do watcher có chặn
  `--min-count` + `require-public`.
