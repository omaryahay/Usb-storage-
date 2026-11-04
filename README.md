# USB Storage Guard

برنامج تجريبي لويندوز 10 وWindows 11 (64-bit)، بواجهة عربية خضراء.

## الوظيفة
- يراقب الأقراص التي يعرضها Windows على أن `BusType = USB`.
- الحد الافتراضي 265 GB عشرياً (265,000,000,000 بايت).
- إذا تجاوز قرص USB الحد، يحاول جعله Read-only ثم Offline باستخدام أوامر Windows Storage.
- لا يهيّئ القرص ولا يحذف ملفاته.
- يتيح إنشاء كلمة مرور محلية عند أول تشغيل وتغييرها من داخل البرنامج.
- يعرض اسم المطوّر: عمر يحي سيلان.

## تنبيه مهم جداً قبل الاستخدام
هذه النسخة **ليست USB Filter Driver** ولا تضمن منع كل وحدات USB. بعض فلاشات USB تُعرّفها بعض الأجهزة على أنها removable media أو BusType مختلف، وقد يرفض Windows أمر `Set-Disk -IsOffline`. وقد توجد فترة قصيرة بين توصيل الجهاز ومحاولة منعه. لذلك لا تعتمد عليها كحل أمني صارم لمنع القراءة والنسخ في جميع الحالات.

لتحقيق منع مضمون على مستوى النظام لكل الفلاشات والهاردات، يلزم تطوير واختبار Windows device/filter driver موقّع، أو استخدام سياسات Windows/حل إدارة أجهزة معتمد. لا توصل أقراصاً تحتوي بيانات حساسة لاختبار هذه النسخة.

## البناء محلياً
يتطلب Windows 10/11 x64 وPython 3.12:
```powershell
python -m pip install --upgrade pip pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name USBStorageGuard usb_storage_guard.py
```
الملف الناتج:
`dist\USBStorageGuard.exe`

## البناء عبر GitHub Actions
ارفع الملفات إلى مستودع GitHub، ثم افتح Actions وشغّل workflow أو ادفع إلى main. حمّل Artifact باسم `USBStorageGuard-Windows-64bit`.

## ملاحظات
- شغّل البرنامج بصلاحيات المسؤول؛ سيطلبها تلقائياً.
- كلمة المرور تُخزّن كقيمة مشتقة PBKDF2 مع salt في `%LOCALAPPDATA%\USBStorageGuard\settings.json`. هذا يمنع تخزينها كنص صريح، لكنه ليس بديلاً عن حساب Windows محمي.
- إيقاف البرنامج يوقف المراقبة الجديدة فقط. الأقراص التي وُضعت Offline تبقى كذلك إلى أن يعيد المسؤول توصيلها أو يجعلها Online يدوياً من إدارة الأقراص/PowerShell.
- اختبر أولاً على قرص USB تجريبي فارغ وغير مهم، وتأكد من إمكانية إعادته Online.
