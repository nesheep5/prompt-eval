# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## このリポジトリの性質

**公開**リポジトリ。Claude Code プラグイン prompt-eval だけを載せる単独リポジトリで、リポジトリ自身がマーケットプレイス（name: `prompt-eval`）を兼ねる。別のスキルはこのリポジトリに足さず、別のリポジトリで作る。

## 書いてはいけないもの

ファイル・コミットメッセージ・author のどこにも、次を入れない。

- ローカルのパス（ホームディレクトリ以下）
- メールアドレス、実名
- 会社名・社内の語彙・顧客名
- 非公開のリポジトリやプロジェクトの名前、そこでの具体的な作業内容

語のリストでは守らない（書いていない語は素通りし、リスト自体が秘密になるため）。push の前の判断レビューで守る。

## 公開前レビュー

push の前に必ず行う。pre-push が記録の有無を確かめ、無ければ止める。

1. push する範囲を決める（初回や force push なら `main` 全体、通常は `origin/main..HEAD`）
2. **新しいサブエージェント**に、`git log -p --format='%an <%ae>%n%B' <範囲>` の出力だけを渡し、「個人・組織・非公開のプロジェクトを特定できる情報、ローカルの環境に依存する記述が無いか」を判断させる。作業の文脈を知らない読み手の方が見落としにくい。注釈付きタグを push するときは `git cat-file tag <タグ>` の出力（tagger とメッセージ）も渡す。サブエージェントにはファイルの変更・コミット・push をさせない
3. 指摘があれば、語を消すのではなく一般化して書き直し、1 からやり直す
4. 問題が無ければ、`.git/publish-review/<push する HEAD の sha>` に要点を書く（何を見て、何が無かったか、指摘と直した内容）。`.git` の中なので公開されない。worktree で作業しているときも、worktree 側（`.git/worktrees/<名前>`）ではなくメインの `.git`（`git rev-parse --git-common-dir`）に置く
5. push はユーザーに確認してから行う

人が自分で確かめて push するときは、`PUBLISH_REVIEWED=1 git push` で記録を省ける。gitleaks と作者の検査は省けない。

## 準備

```bash
git config core.hooksPath git-hooks
git config user.name nesheep5
git config user.email <GitHub の noreply アドレス>
```

コミットは `nesheep5` と GitHub の noreply アドレスで行う（pre-push が author・committer を確かめる）。コミットメッセージに `Claude-Session:` の行（会話の URL）を付けない。`Co-Authored-By` は付けてよい。

## 開発

- プラグイン本体は `plugins/prompt-eval/` に置き、`marketplace.json` のソースは `./plugins/prompt-eval` と書く。ルートに上げると、tests・evals・git-hooks まで利用者の環境に複製される
- ランナー（`plugins/prompt-eval/skills/prompt-eval/scripts/prompt_eval.py`）の依存は、Python 標準ライブラリと claude CLI だけにする
- ランナーのテストは `tests/` に置き、偽の claude（`tests/fake_claude.py`）で走らせる。テストから本物の `claude -p` を呼ばない
- `evals/skill-effect/` は、スキルを使う場合と使わない場合を比べた測定の記録。本物の `claude -p` を 500 回以上呼ぶので、CI では走らせない。題材や判定の決まりを変えたら測り直し、README の「何で確かめたか」の数字を `evals/skill-effect/results.json` と合わせる。結果は、差が出なくてもそのまま書く
- SKILL.md の手順・判定の規則と、README・`references/case-format.md`・ランナーの実装は同じ内容を持つ。1 つを変えたら、ほかも合わせる
- 作者のマシンでは、クローンをローカルのパスでマーケットプレイスとして登録し、元の場所から読ませる。GitHub の形で登録すると cache に複製され、編集が反映されない
- 変更後は `bash tests/validate.sh`（`claude plugin validate`）・`bash tests/git-hooks.test.sh`・`python3 -m unittest discover -s tests` を通す
- push は公開と同じ意味なので、毎回ユーザーに確認する
