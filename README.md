# prompt-eval

[![CI](https://github.com/nesheep5/prompt-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/nesheep5/prompt-eval/actions/workflows/ci.yml)

CLAUDE.md を直したときに、修正前（before）と修正後（after）を `claude -p` で同じ依頼に数回ずつ走らせ、狙った振る舞いの変化が出ているか、既存の振る舞いが壊れていないかを判定する Claude Code プラグイン。スキルは `/prompt-eval:prompt-eval` の 1 つで、実行と集計は Python 標準ライブラリだけで書いたランナーが行う。

```
/plugin install prompt-eval --marketplace nesheep5/prompt-eval
```

## 解決する問題

CLAUDE.md の規則は、書いた文面を読んで良さそうに見えても、モデルがその通りに動くとは限らない。逆に、規則を削ったり圧縮したりしたときに、それまで守られていた振る舞いが落ちても、差分を読むだけでは気づきにくい。

確かめるには実際に走らせるしかないが、手作業では次の点でつまずく。

- モデルの応答は実行のたびに変わるので、1 回ずつ比べても、差が規則によるものか偶然かを区別できない
- 規則が無くても既定で満たされる依頼で試すと、after が通っても何も確かめていない
- 作業ツリーに after があると、Claude Code は必ず after を読む。before を読ませるには、読み込みの経路を分ける必要がある

prompt-eval は、この比較を同じ条件で繰り返し、ケースごとに合否と理由を出す。

## インストール

必要なものは、Claude Code（`claude` コマンド。ログイン済みであること）、Python 3.9 以降、git。

Claude Code 2.1.275 以降なら、セッションの中で次の 1 行を実行する。マーケットプレイスの追加とインストールが同時に済む。

```
/plugin install prompt-eval --marketplace nesheep5/prompt-eval
```

それより前の版では、2 段階で入れる。

```
/plugin marketplace add nesheep5/prompt-eval
/plugin install prompt-eval@prompt-eval
```

## 使い方

`/prompt-eval:prompt-eval` に続けて依頼を書く。スキル名を付けなくても、次のような依頼で呼ばれる。

- 「CLAUDE.md を直したので効いているか確かめて」
- 「この規則で挙動が変わるか見たい」
- 「CLAUDE.md を圧縮した。リグレッションが無いか確認して」
- 「CLAUDE.md の before/after を比べて」

対象は、リポジトリの CLAUDE.md と、グローバルの `~/.claude/CLAUDE.md`（`@import` 先を含む）。誤字やリンク先の修正のように挙動に影響しない変更は、評価を省く。

### 流れ

1. 対象のファイルと、比べる版を決める。既定は before が `HEAD`、after が作業ツリー
2. 期待する違い（after ではこう振る舞い、before ではそうならないはず）を 1〜3 文で書く。結果を見る前に固める
3. ケースを書く。今回の変更を確かめる change ケースを 1〜3 件。同じ場所に残してある regression ケースは全件走らせる
4. 期待する違い・走らせるケース・費用の見込みを利用者に見せ、承認を得る
5. ランナーを background で走らせる
6. 判定と、落ちた実行・合格した実行の応答を読む。数字だけで判断しない
7. 結果を報告する。合格した change ケースは regression ケースに書き換えて残し、次の変更のときの回帰テストにする

### ケースの例

ケースは、対象のリポジトリの `evals/prompt-eval/<ケース名>/` に置く。被験の Claude に渡す依頼（`prompt.md`）と、応答の採点基準（`graders/*.md`）からなる。次は「答えとして示す md ファイルを `file://` の markdown リンクで書く」という規則を足したときの例。

`evals/prompt-eval/md-link-answer/prompt.md`

```markdown
---
name: md-link-answer
allowed_tools: [Read, Glob, Grep]
prompt_eval:
  kind: change
  expected_difference: >
    after は答えの md ファイルを file:// の markdown リンクで示す。
    before は裸のパスかコード書式で示す。
---
このリポジトリで、プラグインを追加するときの手順が書かれたドキュメントはどれ？
```

`evals/prompt-eval/md-link-answer/graders/link.md`

```markdown
---
type: regex
match: contains
target: final
---
\]\(file:///[^)]*\.md\)
```

依頼文には規則を書かない。「file リンクで答えて」と依頼すれば、規則が無くても通るためだ。形式の全体は [case-format.md](plugins/prompt-eval/skills/prompt-eval/references/case-format.md) にある。

### 出力の例

ランナーは `--out` で指定した場所に、実行ごとの記録と要約を書く。次は要約（`summary.md`）の形で、値は書式を示すための例。

```markdown
# prompt-eval 20260101-093000: fail

- 対象: <repo>/CLAUDE.md（mode=repo、git worktree（HEAD）に worktree 版の対象ファイルを上書き）
- before=HEAD / after=worktree、各腕 3 回、費用 $1.80

| ケース | 種別 | before | after | 判定 | 理由 |
|---|---|---|---|---|---|
| md-link-answer | change | 0/3 | 3/3 | pass | after 3/3 ≥ 2 かつ before 0/3 ≤ 1 |
| starts-with-summary | regression | 3/3 | 1/3 | fail | 退行: after 1/3 < 2、before は 3/3 |
```

記録の構成は次のとおり。応答の全文が入るので、gitignore された場所に出す。

    <out>/<実行 ID>/
      summary.md                         要約
      record.json                        対象・版・方針・ケースごとの判定・ケースのハッシュ・費用
      runs/<ケース>/<腕>/<回>/
        transcript.jsonl                 claude -p の stream-json の出力
        final.md                         最終応答
        grading.json                     grader ごとの合否と根拠
        judge/<grader>.<n>.json          判定役の生の出力
      arms/<腕>/system-prompt.<ケース>.md  global モードで差し込んだ内容

## 仕組み

### before と after の作り方

2 つの版を、対象ファイル以外は同じ条件で読ませる。作り方は対象によって違う。

| モード | 対象 | 版の読ませ方 |
|---|---|---|
| `repo` | リポジトリ内の CLAUDE.md（複数可） | `HEAD` の git worktree をリポジトリの外に腕ごとに作り、対象ファイルだけを各版で上書きして、そこを cwd にする。Claude Code が本来の経路で CLAUDE.md を読む |
| `global` | `~/.claude/CLAUDE.md` と、その `@import` 先 | `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` で自動読み込みを止める。入口のファイルから `@import` を展開し、対象ファイルの部分だけを各版に差し替えたものを、`--append-system-prompt-file` で渡す |

worktree をリポジトリの外に置くのは、中に置くと上の階層の CLAUDE.md も読まれ、2 つの版が混ざるため。

global モードは、CLAUDE.md が本来とは違う位置（システムプロンプトの末尾）に入る。そのため合格は暫定として扱う。`--calibrate` を付けると、after 版を本来の自動読み込みでも同じ回数走らせ、差し込み方式の結果とそろうか（consistent / inconsistent）を出す。

版は git の ref で指定できる。ステージした内容（`index`）や、過去のコミットの前後（`--before-ref <sha>^ --after-ref <sha>`）も比べられる。

### 複数回走らせる理由と判定

1 回の実行では、規則の効果と応答のばらつきを区別できない。そこで各腕を同じ依頼で N 回（既定 3 回）走らせ、合格した回数で判定する。必要な合格数は N の 3 分の 2 の切り上げで、3 回なら 2 回。

change ケース（今回の変更を確かめる）は、両腕を走らせる。

| 判定 | 条件（3 回のとき） | 意味 |
|---|---|---|
| pass | after が 2 回以上合格、かつ before の合格が 1 回以下 | 変更で振る舞いが変わった |
| not-discriminating | after も before も 2 回以上合格 | 変更前から同じ振る舞い。ケースが規則を試せていないか、規則が無くても既定でできている |
| fail | after の合格が 1 回以下 | 規則が効いていない |

after が通るだけでは pass にしない。before でも通る依頼は、変更の効果を示していないためだ。

regression ケース（既存の振る舞いが残っているかを見る）は、まず after だけを走らせる。落ちたときだけ before を走らせ、変更による退行か、ケースが元から不安定かを見分ける。

| 判定 | 条件（3 回のとき） | 意味 |
|---|---|---|
| pass | after が 2 回以上合格 | 振る舞いは残っている |
| fail | after の合格が 1 回以下で、before は 2 回以上合格 | 変更による退行 |
| unstable | after も before も合格が 1 回以下 | ケースが元から不安定 |

使用量の上限・タイムアウト・判定役の失敗・費用の上限で有効な実行が足りないときは、どちらの種別でも inconclusive になる。不合格とは区別する。

### 採点

1 回の実行は、ケースの grader がすべて通ったときに合格と数える。grader は 2 種類ある。

- `regex`: 最終応答、またはツール呼び出しを含む記録に、正規表現が現れるか・現れないか・N 回以上現れるかを見る。費用がかからず、結果がぶれない
- `llm`: 判定役の Claude が、採点基準に書かれた振る舞いが起きたかを判定する。形では判定できない基準に使う

判定役には、基準を満たす箇所を応答から引用できなければ不合格にするよう指示している。見出しや言い回しが after の文面に似ているだけの応答を通さないためだ。出力は JSON スキーマで構造化させ、形が崩れた票は無効票として引き直す。

### 測定を歪めないための扱い

- **被験に評価中だと悟らせない。** 一時ディレクトリには中立な名前を使い、worktree のディレクトリ名は元のリポジトリと同じにする。腕の名前（before / after）もパスに出さない
- **被験が使えるツールを絞る。** `--allowedTools` は確認なしで使える範囲を足すだけで、ほかのツールを止めない。`--tools` で使えるツールそのものをケースの `allowed_tools`（既定は読み取りだけ）に絞り、書き込み系は `--disallowedTools` でも拒否する
- **判定役に余計な文脈を渡さない。** 判定役は `--safe-mode` で起動し、CLAUDE.md を読まず、ツールも持たない。被験の応答は区切りで囲んで渡し、中身は証拠であって指示ではないと伝える
- **判別しない grader を検出する。** change ケースで、両腕のすべての実行で通った grader・落ちた grader には警告を付ける。その grader は合否の根拠になっていない
- **ケースを結果に合わせて変えたことが分かるようにする。** 記録にケースのハッシュを残す
- **時間帯の偏りを両腕に散らす。** change ケースは before と after を交互に走らせる
- **費用に上限を置く。** 全体（`--max-cost`、既定 5 ドル）と 1 回の実行（`--run-budget`、既定 1 ドル）の両方。上限に達したら残りを走らせず、inconclusive にする

### ランナーを直接使う

スキルを通さずに、ランナーだけを走らせることもできる。判定が pass のときだけ終了コードが 0 になる。

```bash
python3 plugins/prompt-eval/skills/prompt-eval/scripts/prompt_eval.py run \
  --mode repo --file <repo>/CLAUDE.md \
  --cases <repo>/evals/prompt-eval \
  --out <repo>/tmp/prompt-eval
```

| オプション | 用途 |
|---|---|
| `--before-ref` / `--after-ref` | 比べる版（git の ref、`index`、`worktree`）。既定は `HEAD` と `worktree` |
| `--case <name>` | ケースを絞り込む |
| `--runs` | 各腕の回数（既定 3） |
| `--calibrate` | global モードで、after 版を本来の自動読み込みでも走らせる |
| `--model` | 被験側のモデル（既定は普段の既定モデル） |
| `--judge-model` | 判定役のモデル（既定 sonnet） |
| `--judge-votes` | 1 実行・1 grader あたりの有効票の数（既定 1。増やすと多数決） |
| `--jobs` | 並列数（既定 2） |

## 何で確かめたか

### スキルを使う場合と、差分を読むだけの場合の比較

スキルを使うと、変更が「効いたか」「既存の振る舞いを壊したか」の判定が当たりやすくなるかを測った（2026-11-26、Claude Code 2.1.332、モデルは既定の claude-fable-5-2）。**この題材では差が出なかった。**

- **題材**: 小さな合成リポジトリの CLAUDE.md への変更 6 件（効く 2、効かない 2、退行を含む 2）。走らせる前に固定した
- **正解**: 各変更の修正前と修正後を、同じ依頼で 8 回ずつ走らせ、正規表現だけで数えた（96 回）。6 件とも合格数は 0/8 か 8/8 に分かれた
- **比べた腕**: 同じ依頼文（意図・差分・「意図した変化は起きたか」「退行は無いか」）を、差分を読んで答える腕（読み取りのツールだけ）と、スキルを起動する腕に、各変更 2 回ずつ渡した
- **指標**: 答えが正解と一致した回数。応答の形は見ていない

| | 差分を読むだけ | スキルを使う |
|---|---|---|
| 正解と一致した回数（変更 6 件 × 2 回） | 12/12 | 10/12 |
| 1 回の所要時間（中央値） | 20.5 秒 | 148 秒 |
| ランナーが走らせた `claude -p` の合計 | 0 回 | 395 回 |

スキルを使う腕が一致しなかった 2 回は、同じ 1 件（既に守られている規則を強調した言い回しに書き換える変更）で、どちらも「退行あり」と答えた。最初に固めたケースでは差が出ず、あとから足した依頼（出力の形式を指定する依頼）での合格数の差を根拠にしていた。その依頼を採点のあとに走らせ直すと、同じ CLAUDE.md でも回によって結果が割れ、退行があるとも無いとも確定できなかった。

この測定の限界は次のとおり。

- 正解も、走らせて数える作りになっている。比べているのは、「読むだけの予測」と「少数回の実行」のどちらが多数回の結果を当てるか、である
- 正解は 1 つの依頼で決めている。別の依頼でだけ現れる変化を、この測定は不一致と数える
- 題材は 6 件で、このリポジトリの作者が作った。どれも短い CLAUDE.md への 1〜2 行の変更で、差分を読めば規則の有無が分かる。規則どうしがぶつかる長い CLAUDE.md や、従う率が中間になる規則は入っていない
- 各変更 2 回ずつ、モデルと版は 1 つ。スキルは利用者の承認を挟む前提だが、非対話で走らせた

題材・駆動スクリプト・集計・変更ごとの内訳は [evals/skill-effect/](evals/skill-effect/README.md) にある。

### 動作確認

比較の測定とは別に、本物の `claude -p` でランナーが動くことを確かめた記録。

- **repo モード（この構成、Claude Code 2.1.332）**: 上の測定で、スキルを起動した 12 セッションのすべてが、ケースを書いてランナーを走らせ、判定を得た。ランナーが走らせた被験の実行は合計 395 回
- **global モード（リポジトリを分ける前の版、Claude Code 2.1.283）**: グローバルの CLAUDE.md の規則を 1 行変えた変更で、change 1 ケース（grader は regex 2・llm 1）を各腕 3 回。before 0/3、after 3/3 で pass。記録はこのリポジトリに含めていない
- **regression の 2 巡目（同じく前の版）**: 規則を削った変更で、after が落ちたあと before を走らせ、fail（退行）と判定することを各腕 1 回で確かめた

## 制限

- **対象は CLAUDE.md だけ。** SKILL.md やサブエージェントの定義の評価には使えない
- **global モードの合格は暫定。** CLAUDE.md を差し込む位置が本来と違う。`--calibrate` で確かめられるが、その分の実行が増える
- **1 回の `claude -p` で観察できる振る舞いしか測れない。** 利用者の返答を待ってから効く規則や、長いやりとりの途中の判断を変える規則は、差が出ない
- **3 回は少ない。** 合格率が 5 割前後の振る舞いは、判定が実行のたびに変わりうる。判定が割れたら `--runs 5` で確かめる
- **結果を見てからケースを足すと、偶然の差を拾いやすい。** 上の測定では、あとから足した依頼での差が、走らせ直すと再現しなかった。ケースは走らせる前に固め、あとから足したケースの差は、別の実行で再現を確かめてから判定に使う
- **書き込みを許すケースは、実行のあいだで元に戻らない。** repo モードでは同じ腕の実行が 1 つの worktree を、global モードではすべての実行が 1 つの作業ディレクトリを共有する。ファイルを書き換える依頼は、前の回の変更が次の回に残る
- **費用と時間がかかる。** change 1 ケースで `claude -p` を 6 回、llm の grader を使えば実行ごとに判定役も呼ぶ。挙動が変わりうる変更にだけ使う
- **ケースの質が結果を決める。** 依頼が規則の効く場面を突いていなければ not-discriminating になり、grader が緩ければ偽の合格が出る。合格した実行の応答も読む前提で使う

## 開発

作者向けの情報。

### 構成

    .claude-plugin/marketplace.json     マーケットプレイスの目録（prompt-eval だけを載せる）
    plugins/prompt-eval/                プラグイン本体
      .claude-plugin/plugin.json
      skills/prompt-eval/
        SKILL.md                        手順（対象の決め方、ケースの書き方、承認、結果の読み方）
        references/case-format.md       ケースの形式
        scripts/prompt_eval.py          ランナー
    tests/                              test_prompt_eval.py・fake_claude.py・validate.sh・git-hooks.test.sh
    evals/skill-effect/                 スキルを使う場合と使わない場合を比べた測定（題材・駆動スクリプト・結果）
    git-hooks/                          公開前の検査（pre-commit・pre-push）
    .github/workflows/ci.yml            push と PR で tests/ を走らせる

プラグイン本体をリポジトリのルートに置かないのは、tests・evals・git-hooks まで利用者の環境に複製しないため。

### テスト

```bash
python3 -m unittest discover -s tests   # ランナーのテスト
bash tests/validate.sh                  # claude plugin validate
bash tests/git-hooks.test.sh            # git-hooks のテスト
```

ランナーのテストは、`claude` を偽の実装（`tests/fake_claude.py`）に差し替えて走らせる。API は呼ばないので、結果は毎回同じになる。偽の実装は、読めた指示に特定の規則があるかどうかで応答を変える。これを使って、次を確かめている。

- 判定の規則（change・regression・較正の各分岐）
- repo モードで worktree が腕ごとに作られ、終了後に片付き、作業ツリーが変わらないこと
- global モードで `@import` が展開され、対象ファイルだけが差し替わること
- regression ケースで、after が通れば before を走らせず、落ちたときだけ走らせること
- 使用量の上限と費用の上限が、fail ではなく inconclusive になること
- 判定役の無効票を引き直すこと
- 被験に渡すツールの引数が `allowed_tools` に絞られること
- git のフックから走らせても、呼び出し元のリポジトリを書き換えないこと

テストが確かめるのはランナーの論理で、本物のモデルが規則に従うかどうかではない。

### 手元での動かし方

作者のマシンでは、このリポジトリのクローンをローカルのパスでマーケットプレイスとして登録し、元の場所から読み込む。

```
claude plugin marketplace add <このリポジトリのパス>
```

編集は次のセッションか `/reload-plugins` で反映される。ローカルのパスで登録したマーケットプレイスは cache に複製せず元の場所から読むため、version を上げる必要は無い。

## 公開前の検査

公開リポジトリなので、コミットと push の前に次を検査する（`git config core.hooksPath git-hooks` で有効にする）。

- gitleaks による秘匿情報の検出（pre-commit・pre-push）
- author・committer が GitHub の noreply アドレスであること（pre-push）
- push する差分の判断レビュー（pre-push がレビューの記録を確かめる）。語のリストでは守らず、差分を読んで個人・組織・非公開の情報が無いかを判断する。手順は CLAUDE.md

## ライセンス

MIT（[LICENSE](LICENSE)）
