// Unity queue dispatcher (tools/unity_queue, docs/unity_queue_runner.md).
//
// One Unity batch launch runs several queued jobs:
//   Unity.exe -batchmode -quit -projectPath P -executeMethod UnityQueueDispatcher.RunBatch -unityQueueBatch batch.json
//
// batch.json: {"launchId": "...", "resultsPath": "...", "jobs": [{"id": "...", "executeMethod": "Ns.Type.Method",
//              "args": ["-flag", "value", ...]}]}
//
// Each job's static parameterless method is invoked in turn. A job sees its own arguments and records its exit code
// through AppDomain data (keys below), which the job's class reads through its UnityQueueArgs()/UnityQueueExit()
// shim; a class without that shim is refused (it would read the dispatcher's own command line). An exception, or a
// nonzero UnityQueueExit code, fails that job only; the batch continues. One JSON line per finished job is appended
// to resultsPath (flushed at once), so a Unity crash leaves the jobs it never reached without a result line and the
// Python runner fails them with the crash diagnostic.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using Debug = UnityEngine.Debug;

public static class UnityQueueDispatcher
{
    public const string ArgsKey = "UnityQueue.JobArgs";
    public const string ExitKey = "UnityQueue.ExitCode";

    [Serializable] class Job { public string id; public string executeMethod; public string[] args; }
    [Serializable] class Batch { public string launchId; public string resultsPath; public Job[] jobs; }

    public static void RunBatch()
    {
        string batchPath = null;
        var argv = Environment.GetCommandLineArgs();
        for (int i = 0; i < argv.Length - 1; i++) if (argv[i] == "-unityQueueBatch") batchPath = argv[i + 1];
        if (string.IsNullOrEmpty(batchPath)) { Debug.LogError("UNITY_QUEUE_BATCH_FAILED missing -unityQueueBatch"); EditorApplication.Exit(3); return; }
        Batch batch;
        try { batch = JsonUtility.FromJson<Batch>(File.ReadAllText(batchPath)); }
        catch (Exception e) { Debug.LogError("UNITY_QUEUE_BATCH_FAILED unreadable batch " + batchPath + ": " + e); EditorApplication.Exit(3); return; }
        Debug.Log("UNITY_QUEUE_BATCH_BEGIN " + batch.launchId + " jobs=" + batch.jobs.Length);
        int failed = 0;
        for (int j = 0; j < batch.jobs.Length; j++)
        {
            var job = batch.jobs[j];
            if (j > 0) Reset();
            var sw = Stopwatch.StartNew();
            string status = "ok", error = null;
            int exitCode = 0;
            Debug.Log("UNITY_QUEUE_JOB_BEGIN " + job.id + " " + job.executeMethod);
            var jobArgv = new List<string> { "Unity.exe(unity_queue job " + job.id + ")" };
            jobArgv.AddRange(job.args ?? new string[0]);
            AppDomain.CurrentDomain.SetData(ArgsKey, jobArgv.ToArray());
            AppDomain.CurrentDomain.SetData(ExitKey, null);
            try
            {
                var method = Resolve(job.executeMethod);
                method.Invoke(null, null);
                var code = AppDomain.CurrentDomain.GetData(ExitKey);
                if (code is int c && c != 0) { status = "failed"; exitCode = c; error = "UnityQueueExit(" + c + ")"; }
            }
            catch (Exception e)
            {
                var inner = e is TargetInvocationException && e.InnerException != null ? e.InnerException : e;
                status = "failed"; exitCode = 1; error = inner.GetType().FullName + ": " + inner.Message;
                Debug.LogError("UNITY_QUEUE_JOB_EXCEPTION " + job.id + " " + inner);
            }
            finally
            {
                AppDomain.CurrentDomain.SetData(ArgsKey, null);
                AppDomain.CurrentDomain.SetData(ExitKey, null);
            }
            if (status != "ok") failed++;
            Debug.Log("UNITY_QUEUE_JOB_END " + job.id + " " + status);
            var line = new StringBuilder();
            line.Append("{\"id\":\"").Append(Esc(job.id)).Append("\",\"status\":\"").Append(status)
                .Append("\",\"exitCode\":").Append(exitCode)
                .Append(",\"elapsedSeconds\":").Append((sw.ElapsedMilliseconds / 1000.0).ToString(System.Globalization.CultureInfo.InvariantCulture))
                .Append(",\"error\":").Append(error == null ? "null" : "\"" + Esc(error) + "\"").Append("}\n");
            File.AppendAllText(batch.resultsPath, line.ToString());
        }
        Debug.Log("UNITY_QUEUE_BATCH_END " + batch.launchId + " failed=" + failed);
        EditorApplication.Exit(0);
    }

    static MethodInfo Resolve(string full)
    {
        int dot = full.LastIndexOf('.');
        if (dot <= 0) throw new InvalidOperationException("executeMethod must be Type.Method: " + full);
        string typeName = full.Substring(0, dot), methodName = full.Substring(dot + 1);
        Type type = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            type = asm.GetType(typeName, false);
            if (type != null) break;
        }
        if (type == null) throw new InvalidOperationException("executeMethod type not found (not compiled into the project?): " + typeName);
        var flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
        if (type.GetMethod("UnityQueueArgs", flags) == null || type.GetMethod("UnityQueueExit", flags) == null)
            throw new InvalidOperationException(typeName + " is not queue-compatible: it has no UnityQueueArgs()/UnityQueueExit() shim "
                + "(docs/unity_queue_runner.md); it would read the dispatcher's command line or quit the batch");
        var m = type.GetMethod(methodName, flags, null, Type.EmptyTypes, null);
        if (m == null) throw new InvalidOperationException("executeMethod not found (static, parameterless): " + full);
        return m;
    }

    // Between jobs: drop every loaded bundle (a job that failed before Unload would make the next LoadFromFile of the
    // same bundle fail) and start from an empty scene, so a job never sees the previous job's scene objects.
    static void Reset()
    {
        AssetBundle.UnloadAllAssetBundles(true);
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
    }

    static string Esc(string s)
    {
        var b = new StringBuilder();
        foreach (var ch in s)
        {
            if (ch == '"' || ch == '\\') b.Append('\\').Append(ch);
            else if (ch < 0x20) b.Append("\\u").Append(((int)ch).ToString("x4"));
            else b.Append(ch);
        }
        return b.ToString();
    }
}
