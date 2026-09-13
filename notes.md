# Project descriptions

This project is an app, web-based, to arrange the duty schedule.
This project will contain these main modules:
    - Data: for data management, define holidays, ...
    - Logic: for weights calculation, ensure that all staffs have balanced duty schedule.
    - UX/UI: for non-dev users, in web browser
    - Outputs: for word files creation, help the users to auto-generate `.docx` files with pre-defined format.

# Project structure

```
.
├── archives ## not used, for archiving only
│   ├── (27.7.2026) Danh sách làm cuối tuần tháng 8.2026 CS2NB và nghỉ lễ tại 2 cơ sở.xlsx
│   ├── Danh sách luân chuyển các vị trí công tác trong khoa từ 15.07.2026.pdf
│   ├── TRUC HTNT T9.2026.xls
│   ├── TRUC NOI TRU T9.2026.xls
│   └── Theo dõi trực Lễ đến 2.9.26.xls
├── data
│   ├── duty_weight_data.xlsx
│   └── staff_data.xlsx
├── notebook.ipynb
├── notes.md
├── outputs
├── pyproject.toml
└── scripts
```

# Data and logic

## Staff data

Here is the structure of staff data.

| column         | description                   | data type |
|----------------| ------------------------------|-----------|
| bmo_id         | id of the staff               | str       |
| ho_va_ten      | staff name                    | str       |
| tuoi           | age                           | int       |
| gioi_tinh      | sex                           | categorical ("Nam" OR "Nữ") |
| trinh_do       | certificate                   | categorical ("Đại học" OR "Cao đẳng") |
| vi_tri         | position                      | categorical ("KHHS", "DLS", ...) |
| so_dien_thoai  | phone_number                  | str         |
| mang_thai      | is pregnant?                  | boolean     |
| sinh_de        | is after giving birth?        | boolean     |
| ghi_chu        | extra notes for users         | str         |
| ninh_binh_base | is in Ninh Binh base now, if not -> Hanoi base    | boolean |

Staff data will be used to:
    - Show when users arrange schedule (like a contact-type pop-up, see [UI](#ui))
    - Define the working position
        - Đại học <> Cao đẳng
        - Nhà thuốc <> not Nhà thuốc (all vi_tri are not contain "Nhà thuốc", will be grouped as "Nội trú")
    - Define other privilege, as pregnancy or after giving birth.

## Duty weights

Each duty type has a different weight.

The project will calculate accumulated weights for a month (and **last 2 months**) for each staff -> maintain the balance between staffs.

For example

A staff named Vuong Hoang Hung, currently working at Hanoi base. Here is his shift schedule:
    - 2 normal days -> 2 weights
    - 1 Sunday, but in Ninh Binh base -> 2 * 1.25 = 2.5 weights
    - In total = 5.5 weights.
    - But if he is working at Ninh Binh base -> total: 2 + 2 = 4 weights.

More descriptions, see `data/duty_weight_data.xlsx`

## Calendar

Calendar contains
    - Normal working days: from Monday to Friday.
    - Holidays: according to Vietnamese holidays. **Two sub-types**:
        - General: Nationanl Dependent Day (2/9), World Working Day (1/5), ... -> Repeat every calendar year.
        - Mannually: User can define if a day in a year is a holiday.

Calendar will be used to calculate the weights, see [Duty weights](#duty-weights)

# UI

- The users will see at least two tabs: "data", and "calendar".
    - "data" tab to manage staff or weigt data, define holidays
    - "calendar" to assign duty schedule.
    - boolean data will be shown as checkboxes.

- Templates of UI, Claude will choose.

## data tab

- Data will be showed like excel files (spreadsheets)

## Calendar tab

- Showed as a calendar app
- In each day, we can see in Hanoi and Ninh Binh base: duty staffs, like stacks (different base, different colors)
- User will click in the calendar -> "assign" -> user choose a staff, pop-up style.
    - When the mouse hovers the staff, a pop-up will show the staff info
        - Contact-style information (name, sex, phone number, extra privilege...)
        - Total weights for this month, and last 2 months / average weights for this month of the same certificate staffs. For example, if the staff is "Đại học" -> Show average of this month for "Đại học". Same as "Cao đẳng".

# Outputs and export

This module will be made later