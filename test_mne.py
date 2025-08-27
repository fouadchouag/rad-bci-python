import mne
builtin_montages = mne.channels.get_builtin_montages(descriptions=True)
for montage_name, montage_description in builtin_montages:
    #print(f"{montage_name}: {montage_description}")
    pass

easycap_montage = mne.channels.make_standard_montage("easycap-M1")
print(easycap_montage)

easycap_montage.plot()  # 2D

fig = easycap_montage.plot(kind="3d", show=False)  # 3D
fig.figure.show()
fig = fig.gca().view_init(azim=70, elev=15)  # set view angle for tutorial
