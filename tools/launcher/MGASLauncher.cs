// MGAS 启动器（原生 Windows exe，零依赖、无需安装 Python）
//
// 设计要点：
//   · 纯 .NET Framework 4.x 编译（Windows 10/11 自带，用户不需要装任何运行时）
//   · 只做三件事：环境自检 → 启动内嵌 python 跑 bot_gui.py → 出错时给出可读提示
//   · 不含任何业务逻辑（逻辑全在 Python 侧，便于热更新）
//   · 出错时把完整输出落到 logs/launcher.log，客服排查有据
//
// ⭐⭐⭐ 2026-10-18 **自用版 / 朋友版 由编译期开关决定**（用户口径：
//     「以发布仓为唯一源，**我自用的时候要开启存图功能**」＋「能不能全自动，
//       **我的启动器弄特殊一点**」）
//   ---- 为什么要这样做 ----
//     一个包两用：自己下载来用要**存图**（研究/排查要看帧），发给别人不该存
//     （0.7MB/图，几十张就把硬盘撑满）。
//     原来只能手工删 `friend_mode.flag` 或设环境变量 ⇒ **每次重下/更新都要重搞** ✗
//   ---- 做法 ----
//     本文件用 `#if MGAS_DEV` 包一段：自用版启动器**编译进**这句
//         psi.EnvironmentVariables["MAPBOT_FRIEND"] = "0";
//     ⇒ 自用版 = 存图开 + 精确规划开（= 开发版行为）
//     ⇒ 朋友版（GitHub 上那个 exe）**没有这段字节** ⇒ 保持 `friend_mode.flag` 的朋友版行为 ✓
//   ---- 怎么编自用版 ----
//     python tools\launcher\build_launcher.py --dev
//     ⚠ 产物别覆盖仓里的 MGAS.exe（那个是要发给别人的），脚本会自动改名成
//        MGAS-dev.exe，你把它放进自己的解压目录即可 ✓
//
// 编译（零安装，用系统自带 csc）：
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
//       /target:winexe /platform:anycpu /optimize+ /out:MGAS.exe MGASLauncher.cs

using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using System.Drawing;

namespace MGAS
{
    internal static class Launcher
    {
        private const string AppTitle = "幻想少女公会 · 自动探索";
        private const string Version = "1.0";

        [STAThread]
        private static int Main(string[] args)
        {
            // ⚠ winexe（/target:winexe）**没有控制台**，设 OutputEncoding 会抛
            //   IOException「句柄无效」⇒ 整个启动器一启动就崩（实测踩过）。
            //   必须包在 try 里，且失败可忽略。
            try { Console.OutputEncoding = Encoding.UTF8; } catch { }
            try { Console.InputEncoding = Encoding.UTF8; } catch { }

            string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string logDir = Path.Combine(root, "logs");
            string logFile = Path.Combine(logDir, "launcher.log");

            try
            {
                Directory.CreateDirectory(logDir);
            }
            catch { /* 只读介质：日志失败不影响启动 */ }

            try
            {
                // ── ① 找 python ────────────────────────────────────────────
                string py = FindPython(root);
                if (py == null)
                {
                    Fail(root, logFile,
                        "找不到 Python 运行环境。\n\n" +
                        "这个包应该自带 python\\ 目录。如果你是自己下载源码运行，" +
                        "请先按 README 安装 Python 3.11 并 pip install -r requirements.txt。");
                    return 2;
                }

                // ── ② 找入口脚本 ──────────────────────────────────────────
                string entry = Path.Combine(root, "core", "bot_gui.py");
                if (!File.Exists(entry))
                {
                    Fail(root, logFile,
                        "包不完整：找不到 bot_gui.py。\n\n" +
                        "请重新解压整个压缩包（不要只挑一部分文件出来）。");
                    return 3;
                }

                // ── ②b 完整性预检 ─────────────────────────────────────────
                // 用户实报：解压**还没完成**就双击 ⇒ python 起来时缺 tkinter
                // ⇒ 只看到一句 `ModuleNotFoundError: No module named 'tkinter'`，
                //    完全猜不到是"压缩包没解完"✗
                // ⇒ 起 python 之前先查关键文件，缺哪个就直说缺哪个。
                string missing = CheckIntegrity(root);
                if (missing != null)
                {
                    Fail(root, logFile,
                        "包不完整：缺少 " + missing + "\n\n" +
                        "多半是**解压还没完成**就双击了，或者只解压了一部分。\n\n" +
                        "怎么办：\n" +
                        "  1. 等解压真正结束（进度条走完）再双击\n" +
                        "  2. 还不行就删掉整个文件夹，重新完整解压一次\n" +
                        "  3. 千万别在压缩包预览窗口里直接双击运行");
                    return 4;
                }

                // ── ③ 起进程 ──────────────────────────────────────────────
                var psi = new ProcessStartInfo
                {
                    FileName = py,
                    Arguments = Quote(entry),
                    WorkingDirectory = root,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                psi.EnvironmentVariables["PYTHONUTF8"] = "1";
                // 让子进程别再弹黑窗（GUI 是 tkinter，本身不需要控制台）
                psi.EnvironmentVariables["PYTHONLEGACYWINDOWSSTDIO"] = "0";

#if MGAS_DEV
                // ⭐⭐⭐ 自用版专属（`build_launcher.py --dev` 才编进来）
                //   `MAPBOT_FRIEND=0` ⇒ friend_mode.IS_FRIEND=False
                //     ⇒ 存图勾选**出现**、`SAVE_FIRST_DEFAULT=True`
                //     ⇒ 精确规划也一并开启（= 开发版行为）
                //   ⚠ 朋友版没有这两行（条件编译 ⇒ 那版 exe 里**没有这段字节**）✓
                psi.EnvironmentVariables["MAPBOT_FRIEND"] = "0";
#endif

                var sb = new StringBuilder();
                using (var p = new Process { StartInfo = psi })
                {
                    p.OutputDataReceived += (s, e) => { if (e.Data != null) lock (sb) sb.AppendLine(e.Data); };
                    p.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (sb) sb.AppendLine(e.Data); };
                    p.Start();
                    p.BeginOutputReadLine();
                    p.BeginErrorReadLine();

                    // 前 8 秒是"启动窗口期"：若进程立刻退出，说明环境有问题，给可读提示
                    if (!p.WaitForExit(8000))
                    {
                        // 还在跑 ⇒ 正常。等到它结束（用户关掉 GUI）
                        p.WaitForExit();
                    }

                    string output = "";
                    lock (sb) output = sb.ToString();

                    if (p.ExitCode != 0)
                    {
                        WriteLog(logFile, output, p.ExitCode);
                        // 区分三种失败，给**可操作**的提示（别只丢一句"启动失败"）
                        bool noDeps = output.Contains("ModuleNotFoundError");
                        bool selfContained = Directory.Exists(
                            Path.Combine(root, "python311"));
                        string msg;
                        if (noDeps && !selfContained)
                        {
                            // 源码目录（没有内嵌 python311）⇒ 用户少了依赖
                            msg =
                                "启动失败：缺少 Python 依赖。\n\n" +
                                "**你下载的是源码，不是「下载即用」包。**\n\n" +
                                "两种办法：\n" +
                                "  1.（推荐）去 Releases 下载 MGAS-vX.Y-portable.zip，\n" +
                                "     解压后双击里面的 MGAS.exe —— 那个自带 Python 与全部依赖\n" +
                                "  2. 就想跑源码，先装依赖：\n" +
                                "     pip install -r requirements.txt\n" +
                                "     然后重新双击本文件\n\n" +
                                "详细报错见：" + logFile;
                        }
                        else
                        {
                            msg =
                                "启动失败（退出码 " + p.ExitCode + "）。\n\n" +
                                "常见原因：\n" +
                                "  · 依赖没装全 —— 看 logs\\launcher.log 末尾的报错\n" +
                                "  · 杀毒软件拦截 —— 把本目录加入白名单后重试\n\n" +
                                "日志：" + logFile;
                        }
                        Fail(root, logFile, msg);
                        return p.ExitCode;
                    }
                }
                return 0;
            }
            catch (Exception ex)
            {
                WriteLog(logFile, ex.ToString(), -1);
                Fail(root, logFile, "启动器内部错误：\n\n" + ex.Message +
                                    "\n\n日志：" + logFile);
                return 1;
            }
        }

        /// <summary>检查自带运行时是否完整。返回 null = 齐全，否则返回「缺什么」。</summary>
        /// <remarks>
        /// 起因（用户实报）：解压**没完成**就双击 ⇒ python 起来时缺 tkinter
        ///   ⇒ 只看到 `ModuleNotFoundError: No module named 'tkinter'`
        ///   ⇒ 完全看不出是"压缩包没解完"✗
        /// 只查**关键几个**（全都查要几万个 stat，启动会变慢）：
        ///   · python 本体 + 标准库 tkinter（GUI 必需）
        ///   · _tkinter.pyd / tcl86t.dll / tk86t.dll（tkinter 的原生支撑）
        ///   · 三个主依赖的入口（customtkinter / cv2 / numpy）
        ///   · 数据表与模板目录（少了虽然能开窗，但一跑图就废）
        /// </remarks>
        private static string CheckIntegrity(string root)
        {
            // 只有"自带运行时"的包才查（源码模式没有 python311，跳过）
            if (!Directory.Exists(Path.Combine(root, "python311"))) return null;

            string[] critical =
            {
                @"python311\python311.dll",
                @"python311\Lib\tkinter\__init__.py",
                @"python311\DLLs\_tkinter.pyd",
                @"python311\DLLs\tcl86t.dll",
                @"python311\DLLs\tk86t.dll",
                @"python311\Lib\site-packages\customtkinter\__init__.py",
                @"python311\Lib\site-packages\cv2\__init__.py",
                @"python311\Lib\site-packages\numpy\__init__.py",
                @"data\server_datatable.json",
                // ⚠ 业务代码在 core/（2026-10-17 目录整理）
                @"core\bot_gui.py",
                @"core\explore_loop.py",
                @"core\spots.py",
            };
            foreach (string rel in critical)
            {
                string p = Path.Combine(root, rel);
                if (!File.Exists(p)) return rel;
            }
            if (!Directory.Exists(Path.Combine(root, "templates", "marks")))
                return @"templates\marks\";
            return null;
        }

        /// <summary>找 python.exe。</summary>
        /// <remarks>
        /// ⚠ 顺序说明（两处都踩过坑）：
        ///   正式发布包把依赖**并进** `python311\Lib\site-packages`（不再带 venv），
        ///   所以 ① 必须命中 `python311\python.exe` —— 它既是解释器也带依赖。
        ///   ② venv 只在 `--keep-venv` 调试模式下存在（那种包不可搬家，但本机能跑）。
        ///   ③ 都没有时回落 PATH（开发者直接跑源码的场景）。
        /// </remarks>
        private static string FindPython(string root)
        {
            string[] candidates =
            {
                // ① 正式包：内嵌 python311（依赖已并进它的 site-packages）
                Path.Combine(root, "python311", "python.exe"),
                Path.Combine(root, "python", "python.exe"),
                // ② 调试包：venv（依赖在 venv 里）
                Path.Combine(root, "venv", "Scripts", "python.exe"),
                Path.Combine(root, ".venv", "Scripts", "python.exe"),
            };
            foreach (string c in candidates)
                if (File.Exists(c)) return c;

            // PATH 兜底（开发者自己跑源码时）
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string dir in path.Split(Path.PathSeparator))
            {
                if (string.IsNullOrWhiteSpace(dir)) continue;
                try
                {
                    string p = Path.Combine(dir.Trim().Trim('"'), "python.exe");
                    if (File.Exists(p)) return p;
                }
                catch { }
            }
            return null;
        }

        private static string Quote(string s) { return "\"" + s + "\""; }

        private static void WriteLog(string logFile, string body, int code)
        {
            try
            {
                var sb = new StringBuilder();
                sb.AppendLine("=== MGAS 启动器日志 ===");
                sb.AppendLine("时间：" + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));
                sb.AppendLine("退出码：" + code);
                sb.AppendLine("------------------------");
                sb.AppendLine(body);
                File.AppendAllText(logFile, sb.ToString(), Encoding.UTF8);
            }
            catch { }
        }

        /// <summary>可读的错误弹窗（不是黑框一闪而过）。</summary>
        private static void Fail(string root, string logFile, string message)
        {
            try
            {
                Application.EnableVisualStyles();
                MessageBox.Show(message, AppTitle + " · 启动失败",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch
            {
                try { Console.Error.WriteLine(message); } catch { }
            }
        }
    }
}
