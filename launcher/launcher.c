/* Photo Compressor.exe - starts the bundled Python (runtime\) with photo_compress.py.
 *
 * The launcher embeds python312.dll in-process instead of spawning pythonw.exe, so the
 * window, taskbar button and Task Manager entry all belong to "Photo Compressor.exe"
 * and carry its icon. GUI subsystem: no console window appears.
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

typedef int (*Py_Main_t)(int, wchar_t **);

static void fail(const wchar_t *msg) {
    MessageBoxW(NULL, msg, L"Photo Compressor", MB_OK | MB_ICONERROR);
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE hPrev, PWSTR cmd, int show) {
    (void)hInst; (void)hPrev; (void)cmd; (void)show;
    wchar_t exe[MAX_PATH * 4], dir[MAX_PATH * 4], rt[MAX_PATH * 4], dll[MAX_PATH * 4], script[MAX_PATH * 4];
    DWORD n = GetModuleFileNameW(NULL, exe, MAX_PATH * 4);
    if (n == 0 || n >= MAX_PATH * 4) { fail(L"Cannot determine the program location."); return 1; }
    wcscpy(dir, exe);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    _snwprintf(rt, MAX_PATH * 4, L"%s\\runtime", dir);
    _snwprintf(dll, MAX_PATH * 4, L"%s\\python312.dll", rt);
    _snwprintf(script, MAX_PATH * 4, L"%s\\photo_compress.py", rt);

    if (GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        fail(L"The \"runtime\" folder is missing.\n\nKeep \"Photo Compressor.exe\" inside its folder, next to \"runtime\".");
        return 1;
    }

    /* Use only the bundled runtime, whatever Python the user may have installed. */
    SetEnvironmentVariableW(L"PYTHONHOME", rt);
    SetEnvironmentVariableW(L"PYTHONPATH", NULL);
    SetEnvironmentVariableW(L"PYTHONSTARTUP", NULL);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONNET_PYDLL", dll);
    SetDllDirectoryW(rt);

    HMODULE py = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!py) { fail(L"Could not load runtime\\python312.dll."); return 1; }
    Py_Main_t Py_Main = (Py_Main_t)(void *)GetProcAddress(py, "Py_Main");
    if (!Py_Main) { fail(L"python312.dll has no Py_Main."); return 1; }

    wchar_t *argv[] = { exe, L"-s", script, NULL };
    return Py_Main(3, argv);
}
